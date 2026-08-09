/**
 * Hand-rolled SVG visualisations.
 *
 * No charting dependency: every mark here encodes one number that came out of
 * the interview, and nothing is drawn that a reader cannot act on. A radar of
 * six rubric dimensions and a per-topic bar list is the whole story.
 */
import { DIMENSION_LABEL, scoreColor } from "./ui";
import type { Dimensions } from "../lib/types";

const DIMS: (keyof Dimensions)[] = [
  "technical_accuracy",
  "conceptual_depth",
  "specificity",
  "practical_evidence",
  "communication",
  "relevance",
];

export function RadarChart({ dimensions, size = 260 }: { dimensions: Dimensions; size?: number }) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 46;
  const n = DIMS.length;

  const point = (i: number, value: number) => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
    const radius = (Math.max(0, Math.min(100, value)) / 100) * r;
    return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)] as const;
  };

  const polygon = DIMS.map((d, i) => point(i, dimensions[d]).join(",")).join(" ");
  const average = Math.round(DIMS.reduce((s, d) => s + dimensions[d], 0) / n);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" height={size} role="img"
         aria-label={`Rubric profile, average ${average} of 100`}>
      {[25, 50, 75, 100].map((ring) => (
        <polygon
          key={ring}
          points={DIMS.map((_, i) => point(i, ring).join(",")).join(" ")}
          fill="none"
          stroke="var(--line)"
          strokeWidth={ring === 100 ? 1 : 0.6}
        />
      ))}
      {DIMS.map((_, i) => {
        const [x, y] = point(i, 100);
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--line)" strokeWidth={0.6} />;
      })}

      <polygon
        points={polygon}
        fill="color-mix(in srgb, var(--accent) 22%, transparent)"
        stroke="var(--accent)"
        strokeWidth={1.6}
        strokeLinejoin="round"
      />
      {DIMS.map((d, i) => {
        const [x, y] = point(i, dimensions[d]);
        return <circle key={d} cx={x} cy={y} r={3} fill={scoreColor(dimensions[d])} />;
      })}

      {DIMS.map((d, i) => {
        const [x, y] = point(i, 128);
        const anchor = Math.abs(x - cx) < 6 ? "middle" : x > cx ? "start" : "end";
        const label = DIMENSION_LABEL[d].split(" ");
        return (
          <text key={d} x={x} y={y} textAnchor={anchor} fontSize={9.5} fill="var(--text-dim)">
            {label.map((word, li) => (
              <tspan key={word} x={x} dy={li === 0 ? 0 : 10}>
                {word}
              </tspan>
            ))}
            <tspan x={x} dy={11} fill={scoreColor(dimensions[d])} fontWeight={600} fontSize={10}>
              {dimensions[d]}
            </tspan>
          </text>
        );
      })}
    </svg>
  );
}

export function ScoreRing({ score, size = 128 }: { score: number; size?: number }) {
  const stroke = 9;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const dash = (Math.max(0, Math.min(100, score)) / 100) * circumference;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
         aria-label={`Overall readiness ${score} out of 100`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line-soft)" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={scoreColor(score)}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${dash} ${circumference}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dasharray 900ms cubic-bezier(0.22,1,0.36,1)" }}
      />
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dy="0.06em"
        fontSize={size * 0.3}
        fontWeight={650}
        fill="var(--text)"
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {score}
      </text>
      <text x="50%" y="50%" textAnchor="middle" dy="1.75em" fontSize={10} fill="var(--text-faint)">
        / 100
      </text>
    </svg>
  );
}

/** Score across the interview — shows adaptation, not just a final number. */
export function Sparkline({
  points,
  height = 44,
}: {
  points: { composite: number | null }[];
  height?: number;
}) {
  const values = points.map((p) => p.composite).filter((v): v is number => v != null);
  if (values.length < 2) return null;
  const width = 100;
  const step = width / (values.length - 1);
  const path = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(2)},${(height - (v / 100) * height).toFixed(2)}`)
    .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none"
         role="img" aria-label="Answer scores over the course of the interview">
      <line x1={0} y1={height * 0.28} x2={width} y2={height * 0.28} stroke="var(--line)" strokeDasharray="2 3" strokeWidth={0.5} />
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
      {values.map((v, i) => (
        <circle key={i} cx={i * step} cy={height - (v / 100) * height} r={1.8} fill={scoreColor(v)}
                vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  );
}
