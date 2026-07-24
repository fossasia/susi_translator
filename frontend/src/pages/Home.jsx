import { Hero } from "../components/site/Hero";
import { Marquee } from "../components/site/Marquee";
import { LiveDemo } from "../components/site/LiveDemo";
import { Features } from "../components/site/Features";
import { Sources } from "../components/site/Sources";
import { Manifesto } from "../components/site/Manifesto";
import { Stats } from "../components/site/Stats";
import { UseCases } from "../components/site/UseCases";
import { OpenSource } from "../components/site/OpenSource";

export default function Home() {
  return (
    <div data-testid="home-page">
      <Hero />
      <Marquee />
      <LiveDemo />
      <Features />
      <Sources />
      <Manifesto />
      <Stats />
      <UseCases />
      <OpenSource />
    </div>
  );
}
