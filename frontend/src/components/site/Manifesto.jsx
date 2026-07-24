import { Reveal } from "../Reveal";

const chapters = [
  {
    n: "01",
    title: "Language should never be the barrier.",
    body: "Ideas move faster than translation ever could. SUSI Translator closes that gap in real time, so a speaker in one language reaches an audience in two hundred.",
  },
  {
    n: "02",
    title: "Connect people in their native tongue.",
    body: "From a conference in Berlin to a virtual show streamed worldwide, every listener hears and reads in the language they think in, not a compromise.",
  },
  {
    n: "03",
    title: "Open by principle, not marketing.",
    body: "The entire codebase is open source. Host it yourself, embed it in your event platform, extend it for online meetings. No gatekeeping, no lock-in.",
  },
];

export const Manifesto = () => (
  <section className="relative bg-slate-50 py-28" data-testid="manifesto-section">
    <div className="mx-auto max-w-7xl px-5 sm:px-6">
      <Reveal className="mb-20">
        <span className="text-sm font-semibold uppercase tracking-[0.2em] text-[#0a52ff]">
          Why we built it
        </span>
        <h2 className="mt-4 max-w-3xl font-display text-4xl font-extrabold leading-tight tracking-tight text-slate-900 sm:text-6xl">
          A manifesto for a world that{" "}
          <span className="font-serif-editorial font-normal italic text-slate-500">
            understands each other.
          </span>
        </h2>
      </Reveal>

      <div className="flex flex-col divide-y divide-slate-200">
        {chapters.map((c, i) => (
          <Reveal key={c.n} delay={i * 0.05}>
            <div className="grid gap-6 py-14 md:grid-cols-[auto_1fr_1.2fr] md:items-start md:gap-16">
              <span className="font-display text-6xl font-black text-stroke-blue sm:text-7xl">
                {c.n}
              </span>
              <h3 className="font-display text-3xl font-bold leading-tight tracking-tight text-slate-900">
                {c.title}
              </h3>
              <p className="max-w-xl text-lg leading-relaxed text-slate-600">{c.body}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </div>
  </section>
);
