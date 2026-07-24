import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Lenis from "lenis";
import { Navbar } from "./Navbar";
import { Footer } from "./Footer";

export const SiteLayout = () => {
  const location = useLocation();

  //scroll
  useEffect(() => {
    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
      wheelMultiplier: 1.25,
      touchMultiplier: 2,
    });
    let rafId;
    const raf = (time) => {
      lenis.raf(time);
      rafId = requestAnimationFrame(raf);
    };
    rafId = requestAnimationFrame(raf);
    window.lenis = lenis;

    const onAnchor = (e) => {
      const a = e.target.closest('a[href^="#"]');
      if (!a) return;
      const id = a.getAttribute("href");
      if (id.length > 1) {
        const el = document.querySelector(id);
        if (el) {
          e.preventDefault();
          lenis.scrollTo(el, { offset: -80 });
        }
      }
    };
    document.addEventListener("click", onAnchor);

    return () => {
      cancelAnimationFrame(rafId);
      document.removeEventListener("click", onAnchor);
      lenis.destroy();
      window.lenis = undefined;
    };
  }, []);

  useEffect(() => {
    const { hash } = location;
    if (hash) {
      const t = setTimeout(() => {
        const el = document.querySelector(hash);
        if (el) {
          if (window.lenis) window.lenis.scrollTo(el, { offset: -80 });
          else el.scrollIntoView({ behavior: "smooth" });
        }
      }, 250);
      return () => clearTimeout(t);
    }
    if (window.lenis) window.lenis.scrollTo(0, { immediate: true });
    else window.scrollTo(0, 0);
  }, [location]);

  return (
    <div className="relative min-h-screen bg-white" data-testid="site-layout">
      <Navbar />
      <main>
        <Outlet />
      </main>
      <Footer />
    </div>
  );
};
