import { useEffect, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '@pixiv/three-vrm';
import { Color, Group, Mesh, MeshStandardMaterial, Object3D } from 'three';
import { convertFileSrc } from '@tauri-apps/api/core';
import type { AvatarEmotion } from './useAvatarState';

interface Props {
  modelPath: string;
  scale: number;
  emotion: AvatarEmotion;
  isSpeaking: boolean;
}

const EMOTION_COLORS: Record<AvatarEmotion, string> = {
  neutral: '#6fd5ff',
  thinking: '#ffd36f',
  happy: '#78f0a0',
  surprised: '#ff9e7a',
};

export default function VRMAvatar({ modelPath, scale, emotion, isSpeaking }: Props) {
  const fallbackRef = useRef<Group>(null);
  const leftEyeRef = useRef<Mesh>(null);
  const rightEyeRef = useRef<Mesh>(null);
  const mouthRef = useRef<Mesh>(null);
  const [vrmRoot, setVrmRoot] = useState<Object3D | null>(null);
  const [vrmHandle, setVrmHandle] = useState<any>(null);

  const fallbackMaterial = useMemo(
    () => new MeshStandardMaterial({ color: new Color(EMOTION_COLORS[emotion]), metalness: 0.15, roughness: 0.35 }),
    [emotion],
  );

  useEffect(() => {
    if (!modelPath) {
      setVrmRoot(null);
      setVrmHandle(null);
      return;
    }

    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));

    let disposed = false;
    loader.load(
      convertFileSrc(modelPath),
      (gltf) => {
        if (disposed) return;
        const vrm = (gltf.userData as { vrm?: any }).vrm;
        if (!vrm?.scene) {
          setVrmRoot(null);
          setVrmHandle(null);
          return;
        }
        vrm.scene.rotation.y = Math.PI;
        setVrmRoot(vrm.scene);
        setVrmHandle(vrm);
      },
      undefined,
      () => {
        if (!disposed) {
          setVrmRoot(null);
          setVrmHandle(null);
        }
      },
    );

    return () => {
      disposed = true;
      if (vrmRoot) {
        vrmRoot.traverse((node) => {
          const mesh = node as Mesh & { geometry?: { dispose: () => void }; material?: { dispose: () => void } | { dispose: () => void }[] };
          mesh.geometry?.dispose?.();
          if (Array.isArray(mesh.material)) {
            mesh.material.forEach((material) => material.dispose?.());
          } else {
            mesh.material?.dispose?.();
          }
        });
      }
    };
  }, [modelPath]);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    const blink = 0.15 + 0.85 * Math.abs(Math.sin(t * 0.7));
    const eyeScale = Math.max(0.1, blink);
    const mouthScale = isSpeaking ? 0.6 + Math.abs(Math.sin(t * 9)) * 0.9 : 0.35;
    const bodyScale = 1 + Math.sin(t * 1.6) * 0.02;

    if (fallbackRef.current) {
      fallbackRef.current.position.y = Math.sin(t * 1.6) * 0.03;
      fallbackRef.current.rotation.z = emotion === 'thinking' ? 0.12 : Math.sin(t * 0.5) * 0.03;
      fallbackRef.current.scale.setScalar(scale * bodyScale);
    }

    if (leftEyeRef.current) leftEyeRef.current.scale.y = eyeScale;
    if (rightEyeRef.current) rightEyeRef.current.scale.y = eyeScale;
    if (mouthRef.current) mouthRef.current.scale.y = mouthScale;

    if (vrmHandle?.scene) {
      vrmHandle.scene.position.y = Math.sin(t * 1.6) * 0.03 - 1.35;
      vrmHandle.scene.rotation.z = emotion === 'thinking' ? 0.08 : Math.sin(t * 0.5) * 0.02;
      vrmHandle.scene.scale.setScalar(scale);

      const expressionManager = vrmHandle.expressionManager as any;
      if (expressionManager?.setValue) {
        expressionManager.setValue('happy', emotion === 'happy' ? 1 : 0);
        expressionManager.setValue('surprised', emotion === 'surprised' ? 0.8 : 0);
        expressionManager.setValue('aa', isSpeaking ? 0.35 + Math.abs(Math.sin(t * 10)) * 0.45 : 0);
        expressionManager.setValue('blink', Math.max(0, 1 - eyeScale));
      }
    }
  });

  if (vrmRoot) {
    return <primitive object={vrmRoot} position={[0, -1.35, 0]} scale={scale} />;
  }

  return (
    <group ref={fallbackRef} position={[0, -0.2, 0]}>
      <mesh position={[0, 0.85, 0]} material={fallbackMaterial}>
        <sphereGeometry args={[0.62, 32, 32]} />
      </mesh>
      <mesh position={[0, -0.05, 0]} material={fallbackMaterial}>
        <capsuleGeometry args={[0.45, 0.9, 12, 24]} />
      </mesh>
      <mesh ref={leftEyeRef} position={[-0.22, 0.95, 0.52]}>
        <sphereGeometry args={[0.07, 16, 16]} />
        <meshStandardMaterial color="#0d1117" />
      </mesh>
      <mesh ref={rightEyeRef} position={[0.22, 0.95, 0.52]}>
        <sphereGeometry args={[0.07, 16, 16]} />
        <meshStandardMaterial color="#0d1117" />
      </mesh>
      <mesh ref={mouthRef} position={[0, 0.65, 0.54]}>
        <boxGeometry args={[0.18, 0.08, 0.05]} />
        <meshStandardMaterial color="#0d1117" />
      </mesh>
      <mesh position={[-0.58, 0.05, 0]} rotation={[0, 0, -0.45]} material={fallbackMaterial}>
        <capsuleGeometry args={[0.12, 0.5, 8, 16]} />
      </mesh>
      <mesh position={[0.58, 0.05, 0]} rotation={[0, 0, 0.45]} material={fallbackMaterial}>
        <capsuleGeometry args={[0.12, 0.5, 8, 16]} />
      </mesh>
    </group>
  );
}
