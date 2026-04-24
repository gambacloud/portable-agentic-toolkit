import type { HitlRequest } from "../types";

interface Props {
  hitl: HitlRequest;
  onChoose: (id: string, value: string) => void;
}

export function HitlButtons({ hitl, onChoose }: Props) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[75%] bg-amber-950 border border-amber-700 rounded-xl px-4 py-3">
        <p className="text-sm text-amber-200 mb-3">{hitl.prompt}</p>
        <div className="flex gap-2 flex-wrap">
          {hitl.choices.map((choice) => (
            <button
              key={choice}
              onClick={() => onChoose(hitl.id, choice)}
              className="px-3 py-1.5 text-sm font-medium rounded-lg bg-amber-700 hover:bg-amber-600 text-white transition-colors"
            >
              {choice}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
