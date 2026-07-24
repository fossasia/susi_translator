import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Languages, Github, ArrowUpRight, Menu, X } from "lucide-react";

const sectionLinks = [
  { label: "Product", id: "demo" },
  { label: "Languages", id: "stats" },
  { label: "Use cases", id: "usecases" },
];
const pageLinks = [
  { label: "Docs", to: "/docs" },
  { label: "Pricing", to: "/pricing" },
];

export const Navbar = () => {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const onHome = location.pathname === "/";

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const goSection = (id) => {
    setOpen(false);
    if (onHome) {
      const el = document.getElementById(id);
      if (window.lenis && el) window.lenis.scrollTo(el, { offset: -80 });
      else if (el) el.scrollIntoView({ behavior: "smooth" });
    } else {
      navigate(`/#${id}`);
    }
  };

  return (
    <motion.header
      initial={{ y: -80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
      className="fixed inset-x-0 top-0 z-50 px-4 pt-4 sm:px-6"
      data-testid="navbar"
    >
      <div
        className={`mx-auto flex max-w-7xl items-center justify-between rounded-full px-5 py-3 transition-all duration-500 sm:px-7 ${
          scrolled ? "glass" : "bg-transparent"
        }`}
      >
        <Link to="/" className="flex items-center gap-2.5" data-testid="nav-logo">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#0a52ff] text-white shadow-[0_6px_20px_rgba(10,82,255,0.35)]">
            <Languages className="h-5 w-5" strokeWidth={2.2} />
          </span>
          <span className="font-display text-lg font-extrabold tracking-tight">
            SUSI<span className="text-[#0a52ff]">.</span>Translator
          </span>
        </Link>

        <nav className="hidden items-center gap-8 lg:flex">
          {sectionLinks.map((l) => (
            <button
              key={l.label}
              onClick={() => goSection(l.id)}
              className="group relative text-sm font-medium text-slate-600 transition-colors hover:text-slate-900"
              data-testid={`nav-link-${l.label.toLowerCase().replace(/\s/g, "-")}`}
            >
              {l.label}
              <span className="absolute -bottom-1 left-0 h-px w-0 bg-[#0a52ff] transition-all duration-300 group-hover:w-full" />
            </button>
          ))}
          {pageLinks.map((l) => (
            <Link
              key={l.label}
              to={l.to}
              className="group relative text-sm font-medium text-slate-600 transition-colors hover:text-slate-900"
              data-testid={`nav-link-${l.label.toLowerCase()}`}
            >
              {l.label}
              <span className="absolute -bottom-1 left-0 h-px w-0 bg-[#0a52ff] transition-all duration-300 group-hover:w-full" />
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <a
            href="https://github.com/fossasia/susi_translator"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden items-center gap-2 rounded-full border border-slate-200 bg-white/70 px-4 py-2 text-sm font-medium text-slate-700 transition-all hover:border-slate-300 hover:shadow-sm sm:flex"
            data-testid="nav-github-btn"
          >
            <Github className="h-4 w-4" /> Star
          </a>
          <motion.div whileTap={{ scale: 0.95 }}>
            <Link
              to="/demo"
              className="hidden items-center gap-1.5 rounded-full bg-[#0a52ff] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_8px_24px_rgba(10,82,255,0.3)] transition-shadow hover:shadow-[0_10px_30px_rgba(10,82,255,0.45)] sm:flex"
              data-testid="nav-cta-btn"
            >
              Get started <ArrowUpRight className="h-4 w-4" />
            </Link>
          </motion.div>
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 lg:hidden"
            data-testid="nav-mobile-toggle"
            aria-label="Toggle menu"
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {open && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass mx-auto mt-2 flex max-w-7xl flex-col gap-1 rounded-3xl p-4 lg:hidden"
          data-testid="nav-mobile-menu"
        >
          {sectionLinks.map((l) => (
            <button
              key={l.label}
              onClick={() => goSection(l.id)}
              className="rounded-2xl px-4 py-3 text-left text-base font-medium text-slate-700 hover:bg-white/60"
            >
              {l.label}
            </button>
          ))}
          {pageLinks.map((l) => (
            <Link
              key={l.label}
              to={l.to}
              onClick={() => setOpen(false)}
              className="rounded-2xl px-4 py-3 text-base font-medium text-slate-700 hover:bg-white/60"
            >
              {l.label}
            </Link>
          ))}
          <Link
            to="/demo"
            onClick={() => setOpen(false)}
            className="mt-1 rounded-2xl bg-[#0a52ff] px-4 py-3 text-center text-base font-semibold text-white"
          >
            Get started
          </Link>
        </motion.div>
      )}
    </motion.header>
  );
};
