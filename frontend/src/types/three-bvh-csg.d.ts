declare module "three-bvh-csg" {
  import * as THREE from "three";

  export const ADDITION: number;
  export const SUBTRACTION: number;
  export const INTERSECTION: number;
  export const REVERSE_SUBTRACTION: number;

  export class Brush extends THREE.Mesh {
    constructor(geometry?: THREE.BufferGeometry, material?: THREE.Material | THREE.Material[]);
    prepareGeometry(): void;
  }

  export class Evaluator {
    constructor();
    evaluate(a: Brush, b: Brush, operation: number, target?: Brush): Brush;
    evaluateHierarchy(scope: Brush, target?: Brush): Brush;
    reset(): void;
  }
}
