import { useEffect, useRef } from 'react';
import { useWizardStore } from '../store/wizardStore';
import Step1Welcome from './Step1Welcome';
import Step2Providers from './Step2Providers';
import Step3ApiKey from './Step3ApiKey';
import Step4ModelPick from './Step4ModelPick';
import Step5Channels from './Step5Channels';
import Step6Features from './Step6Features';
import Step7Summary from './Step7Summary';

const STEPS = [Step1Welcome, Step2Providers, Step3ApiKey, Step4ModelPick, Step5Channels, Step6Features, Step7Summary];
const STEP_META = [
  { label: 'Welcome', detail: 'Set the tone for a local-first AI runtime.' },
  { label: 'Providers', detail: 'Choose the routes NeuralClaw can use.' },
  { label: 'Credentials', detail: 'Validate keys and endpoint access.' },
  { label: 'Models', detail: 'Assign primary, fast, and micro roles.' },
  { label: 'Channels', detail: 'Add messaging surfaces if you want them.' },
  { label: 'Features', detail: 'Enable the premium product slices.' },
  { label: 'Launch', detail: 'Save the config and enter the desktop shell.' },
];

export default function WizardShell() {
  const { currentStep, totalSteps, goToStep } = useWizardStore();
  const StepComponent = STEPS[currentStep - 1];
  const stepMeta = STEP_META[currentStep - 1];
  const progress = Math.round((currentStep / totalSteps) * 100);
  const contentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [currentStep]);

  return (
    <div className="wizard-container">
      <div className="wizard-card">
        <div className="wizard-header">
          <div className="wizard-brand">
            <span className="mascot">NC</span>
            <div>
              <div className="wizard-brand-label">NeuralClaw Setup</div>
              <div className="wizard-brand-subtitle">Private desktop operator surface</div>
            </div>
          </div>
          <div className="wizard-progress-copy">
            <span>Step {currentStep} of {totalSteps}</span>
            <strong>{progress}%</strong>
          </div>
        </div>

        <div className="wizard-meta-card">
          <div>
            <div className="eyebrow">Current Phase</div>
            <h1>{stepMeta.label}</h1>
            <p>{stepMeta.detail}</p>
          </div>
          <div className="wizard-steps">
            {STEP_META.map((step, index) => (
              <button
                key={step.label}
                type="button"
                className={`wizard-step-item ${index + 1 <= currentStep ? 'is-available' : ''} ${index + 1 === currentStep ? 'is-current' : ''}`}
                onClick={() => {
                  if (index + 1 <= currentStep) goToStep(index + 1);
                }}
                disabled={index + 1 > currentStep}
              >
                <div
                  className={`wizard-step-dot ${
                    index + 1 < currentStep ? 'completed' : index + 1 === currentStep ? 'active' : ''
                  }`}
                />
                <span>{step.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div ref={contentRef} className="wizard-content" key={currentStep}>
          {StepComponent && <StepComponent />}
        </div>
      </div>
    </div>
  );
}
