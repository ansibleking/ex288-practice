interface Props {
  steps: string[];
  currentIndex: number;
}

export function StepIndicator({ steps, currentIndex }: Props) {
  return (
    <ol className="step-indicator">
      {steps.map((label, i) => {
        const state = i < currentIndex ? "done" : i === currentIndex ? "current" : "upcoming";
        return (
          <li key={label} className={`step step-${state}`}>
            <span className="step-number">{i < currentIndex ? "✓" : i + 1}</span>
            <span className="step-label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
