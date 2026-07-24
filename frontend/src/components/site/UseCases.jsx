import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { Reveal } from "../Reveal";

const cases = [
  {
    tag: "Today",
    title: "Global conferences",
    desc: "Give every attendee live captions and audio in their own language.",
    img: "https://images.unsplash.com/photo-1540575467063-178a50c2df87?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
  },
  {
    tag: "Today",
    title: "Virtual shows & streams",
    desc: "Turn a single broadcast into a multilingual experience across platforms.",
    img: "https://images.pexels.com/photos/8554420/pexels-photo-8554420.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
  },
  {
    tag: "Coming soon",
    title: "Online meetings",
    desc: "Real-time understanding for distributed teams, the next chapter for SUSI.",
    img: "https://images.unsplash.com/photo-1585854467604-cf2080ccef31?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
  },
];

export const UseCases = () => (
  <section id="usecases" className="relative bg-slate-50 py-28" data-testid="usecases-section">
    <div className="mx-auto max-w-7xl px-5 sm:px-6">
      <Reveal className="mb-16 max-w-2xl">
        <span className="text-sm font-semibold uppercase tracking-[0.2em] text-[#0a52ff]">
          Where it shines
        </span>
        <h2 className="mt-4 font-display text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
          Built for anywhere people gather.
        </h2>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-3">
        {cases.map((c, i) => (
          <Reveal key={c.title} delay={i * 0.1}>
            <motion.div
              whileHover={{ y: -8 }}
              transition={{ type: "spring", stiffness: 300, damping: 22 }}
              className="group relative overflow-hidden rounded-[2rem] border border-slate-100 bg-white"
              data-testid={`usecase-card-${i}`}
            >
              <div className="relative h-56 overflow-hidden">
                <img
                  src={c.img}
                  alt={c.title}
                  className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-105"
                />
                <span className="absolute left-4 top-4 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-[#0a52ff] backdrop-blur">
                  {c.tag}
                </span>
              </div>
              <div className="p-7">
                <div className="flex items-start justify-between gap-4">
                  <h3 className="font-display text-2xl font-bold tracking-tight text-slate-900">
                    {c.title}
                  </h3>
                  <ArrowUpRight className="mt-1 h-5 w-5 shrink-0 text-slate-300 transition-colors group-hover:text-[#0a52ff]" />
                </div>
                <p className="mt-3 leading-relaxed text-slate-600">{c.desc}</p>
              </div>
            </motion.div>
          </Reveal>
        ))}
      </div>
    </div>
  </section>
);
