import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { Environment } from '@react-three/drei';
import type { AvatarEmotion } from './useAvatarState';
import VRMAvatar from './VRMAvatar';

interface Props {
  modelPath: string;
  scale: number;
  emotion: AvatarEmotion;
  isSpeaking: boolean;
}

export default function AvatarScene({ modelPath, scale, emotion, isSpeaking }: Props) {
  return (
    <Canvas
      camera={{ position: [0, 0.9, 3.6], fov: 28 }}
      gl={{ alpha: true, antialias: true }}
      style={{ background: 'transparent' }}
    >
      <ambientLight intensity={1.35} />
      <directionalLight position={[2.5, 4, 3]} intensity={2.2} color="#ffffff" />
      <directionalLight position={[-2.2, 1.8, 1.5]} intensity={0.8} color="#8ec5ff" />
      <pointLight position={[0, -1, 2]} intensity={0.8} color="#72f8ff" />
      <Suspense fallback={null}>
        <VRMAvatar
          modelPath={modelPath}
          scale={scale}
          emotion={emotion}
          isSpeaking={isSpeaking}
        />
        <Environment preset="city" />
      </Suspense>
    </Canvas>
  );
}
