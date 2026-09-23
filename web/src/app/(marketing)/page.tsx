import Link from "next/link";
import { buttonClass } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { HeroPreview, TokenStrip, FormulaStrip, ThresholdStrip, ResultsTable, FactList, LectureDemo, RecordCard } from "@/components/landing";

export default function LandingPage() {
  return (
    <>
      {/* 1. Hero: asymmetric split, real component preview on the right */}
      <section className="mx-auto grid max-w-7xl items-center gap-10 px-4 pb-16 pt-14 sm:px-6 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-16 lg:pb-24 lg:pt-20">
        <div>
          <h1 className="balance text-4xl font-semibold leading-[1.05] tracking-tight md:text-5xl lg:text-6xl">
            Watermark the text you generate. Prove it later.
          </h1>
          <p className="pretty mt-5 max-w-[48ch] text-lg text-fg-muted">
            A local tool that tilts a language model toward a keyed green list, then verifies any text against that key
            with a z-test.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/generate" className={buttonClass({ size: "lg" })}>
              Open the app
            </Link>
            <Link href="#how" className={buttonClass({ variant: "secondary", size: "lg" })}>
              How it works
            </Link>
          </div>
        </div>
        <HeroPreview />
      </section>

      {/* 2. How it works: vertical three-step with a real UI fragment each */}
      <section id="how" className="border-t border-line bg-bg-muted/40">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:py-28">
          <h2 className="balance max-w-[24ch] text-3xl font-semibold tracking-tight md:text-4xl">
            Three steps, one secret key
          </h2>
          <ol className="mt-12 space-y-12 lg:space-y-16">
            <Step
              n={1}
              title="Generate with a green list"
              body="At every position a keyed hash splits the vocabulary in half. Green tokens get a small bias before sampling, so the text still reads naturally but leans green."
            >
              <TokenStrip />
            </Step>
            <Step
              n={2}
              title="Count against chance"
              body="The detector rebuilds each green list from the key and counts how many tokens landed there. Without the key, a text lands on green about half the time. The z-score measures how far above that it sits."
            >
              <FormulaStrip />
            </Step>
            <Step
              n={3}
              title="Decide with a threshold"
              body="A z-score above 4 is flagged. Short texts carry too little evidence, so under 100 scored tokens the answer is inconclusive rather than a false comfort."
            >
              <ThresholdStrip />
            </Step>
          </ol>
        </div>
      </section>

      {/* 3. Measured, not claimed */}
      <section id="results" className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:py-28">
        <Reveal>
          <h2 className="balance max-w-[26ch] text-3xl font-semibold tracking-tight md:text-4xl">Measured, not claimed</h2>
          <p className="pretty mt-4 max-w-[60ch] text-fg-muted">
            The thresholds are only a promise until they are tested. The experiment generates every prompt in both modes,
            scores each text, and reports how often watermarked and normal text get flagged.
          </p>
        </Reveal>
        <Reveal delay={0.1} className="mt-8">
          <ResultsTable />
        </Reveal>
        <Reveal delay={0.15} className="mt-6">
          <Link href="/experiments" className="text-sm font-medium text-accent-soft-fg underline-offset-4 hover:underline">
            Run your own batch
          </Link>
        </Reveal>
      </section>

      {/* 4. What it is not: the statement on the left, the three facts behind it on the right */}
      <section className="border-y border-line">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16 lg:py-24">
          <Reveal>
            <p className="pretty max-w-[24ch] text-2xl font-medium leading-snug tracking-tight md:text-3xl">
              MarkText is not an AI-text detector. It recognises only text that this installation generated with its own
              key.
            </p>
            <p className="pretty mt-5 max-w-[44ch] text-fg-muted">
              That limit is the design, and the app says so on every result. Three consequences follow from it.
            </p>
          </Reveal>
          <Reveal delay={0.08}>
            <FactList />
          </Reveal>
        </div>
      </section>

      {/* 5. For lecturers / for researchers: two rows that alternate sides, each with a real fragment */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:py-28">
        <Reveal>
          <h2 className="balance max-w-[24ch] text-3xl font-semibold tracking-tight md:text-4xl">Built for two rooms</h2>
        </Reveal>
        <div className="mt-12 grid items-center gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
          <Reveal>
            <h3 className="text-xl font-semibold tracking-tight md:text-2xl">In the lecture hall</h3>
            <p className="pretty mt-3 max-w-[48ch] text-fg-muted">
              Show the class what a watermark is by running the same prompt twice. Both texts read alike; only one crosses
              the line, and the history keeps the record.
            </p>
            <Workflow
              steps={[
                "Pick a prompt the class knows and generate it once in each mode.",
                "Read both aloud. Nobody can tell them apart.",
                "Detect both. The watermarked one clears z = 4; the other sits at chance.",
              ]}
            />
          </Reveal>
          <Reveal delay={0.08}>
            <LectureDemo />
          </Reveal>
        </div>
        <div className="mt-20 grid items-center gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-16 lg:mt-28">
          <Reveal className="lg:order-1">
            <h3 className="text-xl font-semibold tracking-tight md:text-2xl">In the lab</h3>
            <p className="pretty mt-3 max-w-[48ch] text-fg-muted">
              Every analysis is a row with its seed, parameters and device, so any number in a report can be traced back to
              the run that produced it.
            </p>
            <Workflow
              steps={[
                "Run a batch over the 100 prompts at the lengths you care about.",
                "Filter the history by batch, annotate outliers, export the set as a new CSV.",
                "Report the flagged rate for both modes next to the threshold you chose.",
              ]}
            />
          </Reveal>
          <Reveal delay={0.08} className="lg:order-0">
            <RecordCard />
          </Reveal>
        </div>
      </section>

      {/* 6. Closing call */}
      <section className="border-t border-line bg-bg-muted/40">
        <div className="mx-auto flex max-w-7xl flex-col items-start gap-6 px-4 py-16 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <p className="balance max-w-[36ch] text-2xl font-medium tracking-tight">
            Runs on a laptop. No cloud, no account needed yet.
          </p>
          <Link href="/generate" className={buttonClass({ size: "lg" })}>
            Open the app
          </Link>
        </div>
      </section>
    </>
  );
}

function Step({ n, title, body, children }: { n: number; title: string; body: string; children: React.ReactNode }) {
  return (
    <li className="grid gap-6 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-16">
      <Reveal>
        <div className="flex gap-5">
          <span className="tabular mt-1 font-mono text-sm text-fg-faint">{n}</span>
          <div>
            <h3 className="text-xl font-semibold tracking-tight md:text-2xl">{title}</h3>
            <p className="pretty mt-3 max-w-[60ch] text-fg-muted">{body}</p>
          </div>
        </div>
      </Reveal>
      <Reveal delay={0.08}>
        <div className="lg:pl-0">{children}</div>
      </Reveal>
    </li>
  );
}

function Workflow({ steps }: { steps: string[] }) {
  return (
    <ol className="mt-6 space-y-3">
      {steps.map((t, i) => (
        <li key={i} className="flex gap-4 text-sm">
          <span className="tabular mt-0.5 font-mono text-xs text-fg-faint">{i + 1}</span>
          <span className="pretty text-fg-muted">{t}</span>
        </li>
      ))}
    </ol>
  );
}
