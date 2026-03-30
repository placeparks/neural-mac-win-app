// NeuralClaw Desktop — Wizard Shell (step container + progress)

import { useWizardStore } from '../store/wizardStore';
import Step1Welcome from './Step1Welcome';
import Step2Providers from './Step2Providers';
import Step3ApiKey from './Step3ApiKey';
import Step4ModelPick from './Step4ModelPick';
import Step5Channels from './Step5Channels';
import Step6Features from './Step6Features';
import Step7Summary from './Step7Summary';

const STEPS = [Step1Welcome, Step2Providers, Step3ApiKey, Step4ModelPick, Step5Channels, Step6Features, Step7Summary];

export default function WizardShell() {
  const { currentStep, totalSteps } = useWizardStore();
  const StepComponent = STEPS[currentStep - 1];

  return (
    <div className="wizard-container">
      <div className="wizard-card">
        <div className="wizard-header">
          <span className="mascot">🧠</span>
          <h1>NeuralClaw Setup</h1>
        </div>

        <div className="wizard-steps">
          {Array.from({ length: totalSteps }, (_, i) => (
            <div
              key={i}
              className={`wizard-step-dot ${
                i + 1 < currentStep ? 'completed' : i + 1 === currentStep ? 'active' : ''
              }`}
            />
          ))}
        </div>

        <div className="wizard-content" key={currentStep}>
          {StepComponent && <StepComponent />}
        </div>
      </div>
    </div>
  );
}
