import { useEffect, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '@pixiv/three-vrm';
import { Box3, Color, Group, Mesh, MeshPhysicalMaterial, Object3D, Vector3 } from 'three';
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
  const haloRef = useRef<Mesh>(null);
  const [vrmRoot, setVrmRoot] = useState<Object3D | null>(null);
  const [vrmHandle, setVrmHandle] = useState<any>(null);
  const [vrmFitScale, setVrmFitScale] = useState(1);
  const [vrmYOffset, setVrmYOffset] = useState(-1.25);
  const [vrmXOffset, setVrmXOffset] = useState(0);
  const [vrmZOffset, setVrmZOffset] = useState(0);
  const presentationScale = 0.94 + Math.max(0.5, Math.min(scale, 2)) * 0.08;

  const shellMaterial = useMemo(
    () => new MeshPhysicalMaterial({
      color: new Color(EMOTION_COLORS[emotion]),
      metalness: 0.12,
      roughness: 0.22,
      clearcoat: 0.9,
      clearcoatRoughness: 0.25,
      reflectivity: 0.55,
    }),
    [emotion],
  );
  const limbMaterial = useMemo(
    () => new MeshPhysicalMaterial({
      color: new Color('#dff6ff'),
      metalness: 0.04,
      roughness: 0.38,
      clearcoat: 0.3,
    }),
    [],
  );

  useEffect(() => {
    if (!modelPath) {
      setVrmRoot(null);
      setVrmHandle(null);
      setVrmFitScale(1);
      setVrmYOffset(-1.25);
      setVrmXOffset(0);
      setVrmZOffset(0);
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
        const bounds = new Box3().setFromObject(vrm.scene);
        const size = bounds.getSize(new Vector3());
        const center = bounds.getCenter(new Vector3());
        vrm.scene.rotation.y = Math.PI;
        if (size.y > 0.0001) {
          const targetHeight = 2.35;
          setVrmFitScale(targetHeight / size.y);
          setVrmYOffset(-bounds.min.y - 1.35);
          setVrmXOffset(-center.x);
          setVrmZOffset(-center.z);
        } else {
          setVrmFitScale(1);
          setVrmYOffset(-1.25);
          setVrmXOffset(0);
          setVrmZOffset(0);
        }
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
      fallbackRef.current.position.y = -0.82 + Math.sin(t * 1.6) * 0.045;
      fallbackRef.current.rotation.z = emotion === 'thinking' ? 0.08 : Math.sin(t * 0.5) * 0.025;
      fallbackRef.current.rotation.x = emotion === 'surprised' ? -0.04 : Math.sin(t * 0.35) * 0.01;
      fallbackRef.current.scale.setScalar(0.84 * presentationScale * bodyScale);
    }

    if (leftEyeRef.current) leftEyeRef.current.scale.y = eyeScale;
    if (rightEyeRef.current) rightEyeRef.current.scale.y = eyeScale;
    if (mouthRef.current) mouthRef.current.scale.y = mouthScale;
    if (haloRef.current) {
      haloRef.current.rotation.z += 0.006;
      haloRef.current.scale.setScalar(1 + Math.sin(t * 1.4) * 0.03);
    }

    if (vrmHandle?.scene) {
      vrmHandle.scene.position.x = vrmXOffset;
      vrmHandle.scene.position.y = vrmYOffset + Math.sin(t * 1.6) * 0.03 - 1.35;
      vrmHandle.scene.position.z = vrmZOffset;
      vrmHandle.scene.rotation.z = emotion === 'thinking' ? 0.08 : Math.sin(t * 0.5) * 0.02;
      vrmHandle.scene.scale.setScalar(vrmFitScale * presentationScale);

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
    return <primitive object={vrmRoot} position={[0, -1.35, 0]} scale={vrmFitScale * presentationScale} />;
  }

  return (
    <group ref={fallbackRef} position={[0, -0.82, 0]}>
      <mesh ref={haloRef} position={[0, 1.26, -0.08]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.46, 0.03, 24, 64]} />
        <meshStandardMaterial color="#72f8ff" emissive="#72f8ff" emissiveIntensity={0.35} transparent opacity={0.6} />
      </mesh>
      <mesh position={[0, 1.04, 0]} material={shellMaterial}>
        <sphereGeometry args={[0.44, 32, 32]} />
      </mesh>
      <mesh position={[0, 1.03, 0.22]}>
        <boxGeometry args={[0.46, 0.28, 0.08]} />
        <meshStandardMaterial color="#101925" emissive="#203754" emissiveIntensity={0.5} />
      </mesh>
      <mesh ref={leftEyeRef} position={[-0.12, 1.05, 0.28]}>
        <boxGeometry args={[0.08, 0.08, 0.04]} />
        <meshStandardMaterial color="#8bf6ff" emissive="#8bf6ff" emissiveIntensity={0.95} />
      </mesh>
      <mesh ref={rightEyeRef} position={[0.12, 1.05, 0.28]}>
        <boxGeometry args={[0.08, 0.08, 0.04]} />
        <meshStandardMaterial color="#8bf6ff" emissive="#8bf6ff" emissiveIntensity={0.95} />
      </mesh>
      <mesh ref={mouthRef} position={[0, 0.92, 0.28]}>
        <boxGeometry args={[0.12, 0.04, 0.03]} />
        <meshStandardMaterial color="#ffcf8c" emissive="#ffcf8c" emissiveIntensity={0.5} />
      </mesh>
      <mesh position={[0, 0.28, 0]} material={shellMaterial}>
        <capsuleGeometry args={[0.32, 0.8, 10, 24]} />
      </mesh>
      <mesh position={[0, -0.48, 0.02]} material={limbMaterial}>
        <capsuleGeometry args={[0.2, 0.46, 10, 18]} />
      </mesh>
      <mesh position={[-0.48, 0.18, 0]} rotation={[0, 0, -0.72]} material={limbMaterial}>
        <capsuleGeometry args={[0.08, 0.46, 8, 14]} />
      </mesh>
      <mesh position={[0.48, 0.18, 0]} rotation={[0, 0, 0.72]} material={limbMaterial}>
        <capsuleGeometry args={[0.08, 0.46, 8, 14]} />
      </mesh>
      <mesh position={[-0.16, -0.86, 0]} rotation={[0, 0, 0.08]} material={limbMaterial}>
        <capsuleGeometry args={[0.07, 0.22, 8, 14]} />
      </mesh>
      <mesh position={[0.16, -0.86, 0]} rotation={[0, 0, -0.08]} material={limbMaterial}>
        <capsuleGeometry args={[0.07, 0.22, 8, 14]} />
      </mesh>
      <mesh position={[-0.16, 1.48, -0.02]} rotation={[0, 0, -0.18]} material={limbMaterial}>
        <capsuleGeometry args={[0.03, 0.22, 6, 10]} />
      </mesh>
      <mesh position={[0.16, 1.48, -0.02]} rotation={[0, 0, 0.18]} material={limbMaterial}>
        <capsuleGeometry args={[0.03, 0.22, 6, 10]} />
      </mesh>
      <mesh position={[-0.16, 1.63, -0.02]}>
        <sphereGeometry args={[0.05, 16, 16]} />
        <meshStandardMaterial color="#ffb347" emissive="#ffb347" emissiveIntensity={0.75} />
      </mesh>
      <mesh position={[0.16, 1.63, -0.02]}>
        <sphereGeometry args={[0.05, 16, 16]} />
        <meshStandardMaterial color="#72f8ff" emissive="#72f8ff" emissiveIntensity={0.75} />
      </mesh>
      <mesh position={[0, -1.02, -0.08]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.5, 40]} />
        <meshStandardMaterial color="#06131f" transparent opacity={0.22} />
      </mesh>
    </group>
  );
}
