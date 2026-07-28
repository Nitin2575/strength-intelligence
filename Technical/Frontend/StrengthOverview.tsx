import React from "react";

type MetricCardProps = {
  label: string;
  value: string;
  note: string;
};

function MetricCard({ label, value, note }: MetricCardProps) {
  return (
    <article className="rounded-2xl border border-neutral-800 bg-neutral-950 p-5">
      <p className="text-sm text-neutral-400">{label}</p>
      <p className="mt-2 text-3xl font-semibold text-white">{value}</p>
      <p className="mt-2 text-sm text-neutral-500">{note}</p>
    </article>
  );
}

export default function StrengthOverview() {
  return (
    <main className="min-h-screen bg-black px-6 py-10 text-white">
      <div className="mx-auto max-w-6xl">
        <header className="mb-10">
          <p className="text-sm uppercase tracking-[0.2em] text-neutral-500">
            Strength Intelligence MkII
          </p>
          <h1 className="mt-3 text-4xl font-semibold">
            Your training, explained.
          </h1>
          <p className="mt-3 max-w-2xl text-neutral-400">
            Connect workout performance with sleep, recovery, and daily activity.
          </p>
        </header>

        <section className="grid gap-4 md:grid-cols-4">
          <MetricCard
            label="Sessions analyzed"
            value="42"
            note="Last 12 weeks"
          />
          <MetricCard
            label="Overload rate"
            value="61%"
            note="Eligible exercise sessions"
          />
          <MetricCard
            label="Plan completion"
            value="89%"
            note="Up 4% from prior block"
          />
          <MetricCard
            label="Performance score"
            value="1.04"
            note="Above recent baseline"
          />
        </section>

        <section className="mt-6 rounded-2xl border border-neutral-800 bg-neutral-950 p-6">
          <p className="text-sm text-neutral-500">Current recommendation</p>
          <h2 className="mt-2 text-2xl font-medium">
            Progress incline dumbbell press
          </h2>
          <p className="mt-3 max-w-3xl text-neutral-400">
            You completed the target in two consecutive sessions while keeping
            average effort stable. Recent recovery signals are near baseline.
          </p>
          <div className="mt-5 flex items-center gap-3">
            <span className="rounded-full border border-neutral-700 px-3 py-1 text-sm">
              Try 85 lb
            </span>
            <span className="text-sm text-neutral-500">
              Moderate confidence
            </span>
          </div>
        </section>
      </div>
    </main>
  );
}
