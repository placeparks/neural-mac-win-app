import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import type { AvatarEmotion } from './useAvatarState';
import VRMAvatar from './VRMAvatar';

interface Props {
  modelPath: string;
  scale: number;
  emotion: AvatarEmotion;
  isSpeaking: boolean;
  collaborationPulse?: boolean;
  activityLevel?: number;
}

export default function AvatarScene({ modelPath, scale, emotion, isSpeaking, collaborationPulse = false, activityLevel = 0 }: Props) {
  return (
    <Canvas
      camera={{ position: [0, 0.55, 5.1], fov: 24 }}
      dpr={[1, 1.35]}
      gl={{ alpha: true, antialias: false, powerPreference: 'low-power' }}
      performance={{ min: 0.6 }}
      style={{ background: 'transparent' }}
    >
      <ambientLight intensity={1.2} />
      <directionalLight position={[2.5, 4, 3]} intensity={1.9} color="#ffffff" />
      <directionalLight position={[-2.2, 1.8, 1.5]} intensity={0.95} color="#8ec5ff" />
      <pointLight position={[0, 0.5, 2.4]} intensity={1.05} color="#72f8ff" />
      <pointLight position={[0, -2, 1.8]} intensity={0.45} color="#ffdca8" />
      <Suspense fallback={null}>
        <VRMAvatar
          modelPath={modelPath}
          scale={scale}
          emotion={emotion}
          isSpeaking={isSpeaking}
          collaborationPulse={collaborationPulse}
          activityLevel={activityLevel}
        />
      </Suspense>
    </Canvas>
  );
}
