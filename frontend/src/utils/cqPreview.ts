/**
 * CadQuery → Three.js cumulative CSG preview utility.
 *
 * Coordinate mapping:
 *   CQ X  →  Three X  (same)
 *   CQ Y  →  Three -Z  (Three Z = -CQ Y)
 *   CQ Z  →  Three Y   (both "up")
 *
 * CQ box(W, D, H)  →  Three BoxGeometry(W, H, D)
 *   W = length (CQ X / Three X)
 *   D = depth  (CQ Y / Three -Z)
 *   H = height (CQ Z / Three Y)
 *
 * Workplane pushPoints on each face:
 *   >Z  U=CQ_X  V=CQ_Y  →  Three (U,  H/2, -V)   drill axis: -Y CQ = Three Y
 *   <Z  U=CQ_X  V=CQ_Y  →  Three (U, -H/2, -V)
 *   >X  U=CQ_Y  V=CQ_Z  →  Three (W/2,  V, -U)   drill axis: -X CQ = Three -X
 *   <X  U=CQ_Y  V=CQ_Z  →  Three (-W/2, V, -U)
 *   >Y  U=CQ_X  V=CQ_Z  →  Three (U,   V, -D/2)  drill axis: -Y CQ = Three +Z
 *   <Y  U=CQ_X  V=CQ_Z  →  Three (U,   V,  D/2)  drill axis: +Y CQ = Three -Z
 */

import * as THREE from "three";
import { Evaluator, Brush, SUBTRACTION } from "three-bvh-csg";
import type { BuildStep } from "../components/BuildPlanPanel";

export interface CqPreviewResult {
  geometry: THREE.BufferGeometry;
  notes: string[];
}

// ---------------------------------------------------------------------------
// Parsers
// ---------------------------------------------------------------------------

const f = (m: RegExpMatchArray, i: number) => parseFloat(m[i] ?? "0");

function parseBox(code: string) {
  const m = code.match(/\.box\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/);
  return m ? { w: f(m, 1), d: f(m, 2), h: f(m, 3) } : null;
}

function parseCylinder(code: string) {
  // Extract the full .cylinder(...) argument string first
  const callMatch = code.match(/\.cylinder\(([^)]+)\)/);
  if (callMatch) {
    const args = callMatch[1]!;
    // Named keyword arguments (any order): radius=R, height=H
    const rKw = args.match(/radius\s*=\s*([\d.]+)/);
    const hKw = args.match(/height\s*=\s*([\d.]+)/);
    if (rKw && hKw) return { r: parseFloat(rKw[1]!), h: parseFloat(hKw[1]!) };
    // CadQuery positional signature: .cylinder(height, radius, ...)
    // height is the FIRST positional arg, radius is the SECOND.
    const posNums = [...args.matchAll(/([\d.]+(?:\.\d+)?)/g)].map((m) => parseFloat(m[1]!));
    if (posNums.length >= 2) return { r: posNums[1]!, h: posNums[0]! };
    if (posNums.length === 1) return { r: posNums[0]!, h: posNums[0]! };
  }
  // Fallback: .circle(r).extrude(h) — radius then height (correct order)
  const m = code.match(/\.circle\(\s*([\d.]+)\s*\)[\s\S]*?\.extrude\(\s*([\d.]+)\s*\)/);
  if (m) return { r: f(m, 1), h: f(m, 2) };
  return null;
}

function parseFace(code: string): string {
  const m = code.match(/\.faces\(\s*["']([<>][XYZxyz])["']/);
  return m ? (m[1] ?? ">Z").toUpperCase() : ">Z";
}

function parsePushPoints(code: string): { x: number; y: number }[] {
  const m = code.match(/\.pushPoints\(\s*\[([\s\S]*?)\]/);
  if (!m) return [{ x: 0, y: 0 }];
  const pts: { x: number; y: number }[] = [];
  for (const p of m[1]!.matchAll(/\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/g)) {
    pts.push({ x: parseFloat(p[1] ?? "0"), y: parseFloat(p[2] ?? "0") });
  }
  return pts.length ? pts : [{ x: 0, y: 0 }];
}

function parseHole(code: string) {
  const m = code.match(/\.hole\(\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/);
  return m ? { d: f(m, 1), depth: m[2] ? f(m, 2) : null } : null;
}

function parseRect(code: string) {
  const m = code.match(/\.rect\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)/);
  return m ? { w: f(m, 1), h: f(m, 2) } : null;
}

function parseCutBlind(code: string): number | null {
  // Positional (with optional trailing args): .cutBlind(-15), .cutBlind(15), .cutBlind(-15, True)
  const m1 = code.match(/\.cutBlind\(\s*(-?[\d.]+)\s*[,)]/);
  if (m1) return Math.abs(f(m1, 1));
  // Named parameter: .cutBlind(distanceToCut=-15) or .cutBlind(distance=-15)
  const m2 = code.match(/\.cutBlind\([^)]*(?:distanceToCut|distance)\s*=\s*(-?[\d.]+)/);
  if (m2) return Math.abs(f(m2, 1));
  return null;
}

/** Returns all radii from .circle(r) calls in order (outermost approaches) */
function parseCircles(code: string): number[] {
  const radii: number[] = [];
  for (const m of code.matchAll(/\.circle\(\s*([\d.]+)\s*\)/g)) {
    radii.push(parseFloat(m[1] ?? "0"));
  }
  return radii;
}

function parseSlot2D(code: string) {
  const m = code.match(/\.slot2D\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)/);
  return m ? { len: f(m, 1), w: f(m, 2) } : null;
}

function parseCenter(code: string) {
  const m = code.match(/\.center\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/);
  return m ? { x: f(m, 1), y: f(m, 2) } : null;
}

/** Extract positions from .transformed(offset=cq.Vector(x, y, ...)) patterns */
function parseTransformedPoints(code: string): { x: number; y: number }[] {
  const pts: { x: number; y: number }[] = [];
  for (const m of code.matchAll(/\.transformed\([^)]*offset\s*=\s*(?:cq\.Vector\()?\s*([-\d.]+)\s*,\s*([-\d.]+)/g)) {
    pts.push({ x: parseFloat(m[1]!), y: parseFloat(m[2]!) });
  }
  return pts;
}

/**
 * Extract (x, y) tuples from a list literal that contains only numeric 2D tuples.
 * e.g. [(60.1, 60.1), (-60.1, 60.1), (-60.1, -60.1), (60.1, -60.1)]
 */
function extractTupleList(code: string): { x: number; y: number }[] {
  const pts: { x: number; y: number }[] = [];
  const listMatch = code.match(/\[(?:\s*\(\s*-?[\d.]+\s*,\s*-?[\d.]+\s*\)\s*,?\s*)+\]/);
  if (!listMatch) return pts;
  for (const m of listMatch[0].matchAll(/\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/g)) {
    pts.push({ x: parseFloat(m[1]!), y: parseFloat(m[2]!) });
  }
  return pts;
}

// ---------------------------------------------------------------------------
// Coordinate helpers
// ---------------------------------------------------------------------------

interface BodyDims { w: number; d: number; h: number }

/**
 * Convert workplane pushPoint (u, v) on face `face` to a Three.js
 * cutter cylinder transform.
 *
 * Returns { pos, rot, height } where the CylinderGeometry default axis is Y.
 */
function cutterTransform(
  face: string,
  pt: { x: number; y: number },
  dims: BodyDims,
  cutDepth: number | null, // null = through-all
): { pos: THREE.Vector3; rot: THREE.Euler; height: number } {
  const { w: W, d: D, h: H } = dims;
  const thru = cutDepth === null;
  const d = cutDepth ?? 0;
  const EPS = 0.2; // overshoot for clean boolean

  switch (face) {
    case ">Z":
      return {
        pos: new THREE.Vector3(pt.x, thru ? 0 : H / 2 - d / 2, -pt.y),
        rot: new THREE.Euler(0, 0, 0),
        height: thru ? H + EPS * 2 : d + EPS,
      };
    case "<Z":
      return {
        pos: new THREE.Vector3(pt.x, thru ? 0 : -H / 2 + d / 2, -pt.y),
        rot: new THREE.Euler(0, 0, 0),
        height: thru ? H + EPS * 2 : d + EPS,
      };
    case ">X":
      // Workplane on +X face: U=CQ_Y, V=CQ_Z
      // CQ(W/2, u, v) → Three(W/2, v, -u)
      // Drill axis: -X CQ → -X Three → rot Y→X: PI/2 around Z
      return {
        pos: new THREE.Vector3(thru ? 0 : W / 2 - d / 2, pt.y, -pt.x),
        rot: new THREE.Euler(0, 0, Math.PI / 2),
        height: thru ? W + EPS * 2 : d + EPS,
      };
    case "<X":
      return {
        pos: new THREE.Vector3(thru ? 0 : -W / 2 + d / 2, pt.y, -pt.x),
        rot: new THREE.Euler(0, 0, Math.PI / 2),
        height: thru ? W + EPS * 2 : d + EPS,
      };
    case ">Y":
      // Workplane on +Y face (CQ) = Three -Z face
      // U=CQ_X → Three X, V=CQ_Z → Three Y
      // CQ(u, D/2, v) → Three(u, v, -D/2)
      // Drill axis: -Y CQ → +Z Three → rot Y→+Z: PI/2 around X
      return {
        pos: new THREE.Vector3(pt.x, pt.y, thru ? 0 : -D / 2 + d / 2),
        rot: new THREE.Euler(Math.PI / 2, 0, 0),
        height: thru ? D + EPS * 2 : d + EPS,
      };
    case "<Y":
      // Drill axis: +Y CQ → -Z Three → rot Y→-Z: -PI/2 around X
      return {
        pos: new THREE.Vector3(pt.x, pt.y, thru ? 0 : D / 2 - d / 2),
        rot: new THREE.Euler(-Math.PI / 2, 0, 0),
        height: thru ? D + EPS * 2 : d + EPS,
      };
    default:
      return {
        pos: new THREE.Vector3(pt.x, thru ? 0 : H / 2 - d / 2, -pt.y),
        rot: new THREE.Euler(0, 0, 0),
        height: thru ? H + EPS * 2 : d + EPS,
      };
  }
}

// ---------------------------------------------------------------------------
// CSG helpers
// ---------------------------------------------------------------------------

let _evaluator: Evaluator | null = null;
function getEvaluator(): Evaluator {
  return (_evaluator ??= new Evaluator());
}

function makeBrush(geo: THREE.BufferGeometry, pos?: THREE.Vector3, rot?: THREE.Euler): Brush {
  const b = new Brush(geo);
  if (pos) b.position.copy(pos);
  if (rot) b.rotation.copy(rot);
  b.updateMatrixWorld(true);
  return b;
}

function safeCut(baseBrush: Brush, cutterBrush: Brush, notes: string[], stepSeq: string): Brush | null {
  try {
    const result = new Brush();
    getEvaluator().evaluate(baseBrush, cutterBrush, SUBTRACTION, result);
    result.geometry.computeVertexNormals();
    return result;
  } catch {
    notes.push(`Step ${stepSeq}: ブール演算に失敗（近似）`);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

/**
 * Build a cumulative Three.js geometry from step 1 through `upToSeq`
 * using client-side CSG (three-bvh-csg).
 */
export function buildCumulativePreview(
  allSteps: BuildStep[],
  upToSeq: string,
): CqPreviewResult {
  const notes: string[] = [];
  const steps = [...allSteps]
    .filter((s) => s.step_seq <= upToSeq)
    .sort((a, b) => a.step_seq.localeCompare(b.step_seq));

  let baseBrush: Brush | null = null;
  let dims: BodyDims = { w: 50, d: 30, h: 10 };

  for (const step of steps) {
    const code = step.cq_code ?? "";
    try {
      switch (step.step_type) {
        // -------- Base body --------
        case "base_body": {
          const box = parseBox(code);
          if (box) {
            dims = box;
            const geo = new THREE.BoxGeometry(box.w, box.h, box.d);
            geo.computeVertexNormals();
            baseBrush = makeBrush(geo);
          } else {
            const cyl = parseCylinder(code);
            if (cyl) {
              dims = { w: cyl.r * 2, d: cyl.r * 2, h: cyl.h };
              const geo = new THREE.CylinderGeometry(cyl.r, cyl.r, cyl.h, 64);
              geo.computeVertexNormals();
              baseBrush = makeBrush(geo);
            }
          }
          break;
        }

        // -------- Holes --------
        case "hole_through":
        case "hole_blind":
        case "tapped_hole": {
          if (!baseBrush) break;
          const hole = parseHole(code);
          const face = parseFace(code);

          if (hole) {
            // Standard .hole() path
            let pts = parsePushPoints(code);
            // If parsePushPoints only found default origin (e.g. positions were computed variables),
            // try extracting from an explicit tuple list in the code
            const firstPt = pts[0];
            if (pts.length === 1 && firstPt !== undefined && firstPt.x === 0 && firstPt.y === 0) {
              const listPts = extractTupleList(code);
              if (listPts.length > 0) pts = listPts;
            }
            for (const pt of pts) {
              const { pos, rot, height } = cutterTransform(face, pt, dims, hole.depth);
              const cylGeo = new THREE.CylinderGeometry(hole.d / 2, hole.d / 2, height, 32);
              const cutter = makeBrush(cylGeo, pos, rot);
              const result = safeCut(baseBrush, cutter, notes, step.step_seq);
              if (result) baseBrush = result;
            }
          } else {
            // Fallback: handle result.cut(cq.Workplane().cylinder(...)) pattern
            const cyl = parseCylinder(code);
            if (cyl) {
              // Try .transformed(offset=cq.Vector(x, y, z)) positions first
              let pts = parseTransformedPoints(code);
              // If none, try explicit tuple list
              if (pts.length === 0) pts = extractTupleList(code);
              // If still none, fall back to origin
              if (pts.length === 0) pts = [{ x: 0, y: 0 }];
              for (const pt of pts) {
                const { pos, rot, height } = cutterTransform(face, pt, dims, null); // through-all
                const cylGeo = new THREE.CylinderGeometry(cyl.r, cyl.r, height, 32);
                const cutter = makeBrush(cylGeo, pos, rot);
                const result = safeCut(baseBrush, cutter, notes, step.step_seq);
                if (result) baseBrush = result;
              }
            } else {
              notes.push(`Step ${step.step_seq}: 穴寸法を解析できず`);
            }
          }
          break;
        }

        // -------- Slot --------
        case "slot": {
          if (!baseBrush) break;
          const slot = parseSlot2D(code);
          if (!slot) { notes.push(`Step ${step.step_seq}: 長穴を解析できず`); break; }
          const face = parseFace(code);
          const thru = /cutThruAll/.test(code);
          const depth = thru ? null : parseCutBlind(code);
          const centerOff = parseCenter(code) ?? { x: 0, y: 0 };
          const pts = parsePushPoints(code);
          const origin = pts[0] ?? { x: 0, y: 0 };
          const pt = { x: origin.x + centerOff.x, y: origin.y + centerOff.y };
          const { pos, rot, height } = cutterTransform(face, pt, dims, depth);
          // Approx: box cutter (rounded ends omitted)
          const slotGeo = new THREE.BoxGeometry(slot.w, height, slot.len);
          const cutter = makeBrush(slotGeo, pos, rot);
          const result = safeCut(baseBrush, cutter, notes, step.step_seq);
          if (result) {
            baseBrush = result;
            notes.push(`Step ${step.step_seq}: 長穴端部（R）は矩形で近似`);
          }
          break;
        }

        // -------- Pocket --------
        case "pocket": {
          if (!baseBrush) break;
          // depth: try code first, then parameters fallback
          let depth = parseCutBlind(code);
          if (!depth) {
            const p = step.parameters as Record<string, { value: unknown }> | undefined;
            const dv = p?.depth?.value ?? p?.cut_depth?.value ?? p?.pocket_depth?.value;
            if (typeof dv === "number" && dv > 0) depth = dv;
          }
          if (!depth) { notes.push(`Step ${step.step_seq}: ポケットを解析できず`); break; }
          const face = parseFace(code);
          const centerOff = parseCenter(code) ?? { x: 0, y: 0 };
          const pts = parsePushPoints(code);
          const origin = pts[0] ?? { x: 0, y: 0 };
          const pt = { x: origin.x + centerOff.x, y: origin.y + centerOff.y };
          const { pos, rot, height } = cutterTransform(face, pt, dims, depth);
          const rect = parseRect(code);
          if (rect) {
            // Rectangular pocket
            const pocketGeo = new THREE.BoxGeometry(rect.w, height, rect.h);
            const cutter = makeBrush(pocketGeo, pos, rot);
            const result = safeCut(baseBrush, cutter, notes, step.step_seq);
            if (result) baseBrush = result;
          } else {
            // Circular pocket: .circle(r).cutBlind(d) or annular .circle(R).circle(r).cutBlind(d)
            const circles = parseCircles(code);
            // radius fallback: try parameters when .circle() uses a variable name
            let outerR: number | null = circles.length >= 1 ? Math.max(...circles) : null;
            if (outerR === null) {
              const p = step.parameters as Record<string, { value: unknown }> | undefined;
              const diam = p?.diameter?.value ?? p?.outer_diameter?.value;
              const rad = p?.radius?.value ?? p?.outer_radius?.value;
              if (typeof diam === "number" && diam > 0) outerR = diam / 2;
              else if (typeof rad === "number" && rad > 0) outerR = rad;
            }
            if (outerR !== null) {
              const cylGeo = new THREE.CylinderGeometry(outerR, outerR, height, 64);
              const cutter = makeBrush(cylGeo, pos, rot);
              const result = safeCut(baseBrush, cutter, notes, step.step_seq);
              if (result) {
                baseBrush = result;
                if (circles.length >= 2) {
                  const innerD = Math.min(...circles) * 2;
                  notes.push(`Step ${step.step_seq}: 環状ポケット（内側φ${innerD}mmの残留部は省略）`);
                }
              }
            } else {
              notes.push(`Step ${step.step_seq}: ポケットを解析できず`);
            }
          }
          break;
        }

        // -------- Edge treatments (cannot simulate) --------
        case "fillet":
        case "chamfer":
          notes.push(`${step.step_name}: エッジ処理はプレビューでは省略`);
          break;

        default:
          break;
      }
    } catch (e) {
      notes.push(`Step ${step.step_seq}: エラー`);
      console.warn("[cqPreview]", step.step_seq, e);
    }
  }

  if (!baseBrush) {
    const fallback = new THREE.BoxGeometry(dims.w, dims.h, dims.d);
    return { geometry: fallback, notes };
  }

  // Extract geometry (Brush extends Mesh, geometry is a BufferGeometry)
  const geo = baseBrush.geometry as THREE.BufferGeometry;
  return { geometry: geo, notes };
}
