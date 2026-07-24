const items = [
  "200+ LANGUAGES",
  "TRULY OPEN SOURCE",
  "35+ VOICES",
  "REAL-TIME",
  "ANY AI MODEL",
  "SPEECH TO TEXT",
  "TEXT TO SPEECH",
  "HLS · VIMEO · TWITCH",
];

export const Marquee = () => {
  const row = [...items, ...items];
  return (
    <section
      className="relative overflow-hidden border-y border-slate-100 bg-white py-10"
      data-testid="marquee-section"
    >
      <div className="flex w-max animate-marquee gap-10 whitespace-nowrap">
        {row.map((t, i) => (
          <span key={i} className="flex items-center gap-10">
            <span
              className={`font-display text-4xl font-extrabold tracking-tight sm:text-6xl ${
                i % 2 === 0 ? "text-slate-900" : "text-stroke-blue"
              }`}
            >
              {t}
            </span>
            <span className="text-3xl text-[#0a52ff] sm:text-5xl">✦</span>
          </span>
        ))}
      </div>
    </section>
  );
};
