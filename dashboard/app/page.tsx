import { library, type Subject } from "@/lib/library";
import HeroCanvas from "./home/HeroCanvas";
import Showcase from "./home/Showcase";
import AskDemo from "./home/AskDemo";
import { CountUp, Magnetic, Reveal } from "./home/motion";

export const dynamic = "force-dynamic";

const STEPS = [
  ["01", "Retrieve", "Hybrid search over your trusted library and the open web: dense embeddings, keywords and a cross-encoder reranker pick the best passages."],
  ["02", "Draft", "A local Qwen2.5-7B writes one fact per sentence, each citing the passage it comes from."],
  ["03", "Verify", "An independent DeBERTa-v3-large NLI model checks every sentence against an exact quote. No quote, no sentence."],
  ["04", "Repair", "Failing sentences trigger a fresh search and are rewritten against their closest quote, or dropped."],
];

export default async function Home() {
  let subjects: Subject[] = [];
  try { subjects = await library(); } catch {}
  const topics = subjects.flatMap((s) => s.topics);
  const articles = topics.reduce((n, t) => n + t.articles.length, 0);
  const verified = topics.reduce((n, t) => n + (t.verified || 0), 0);

  return (
    <div className="home">
      <section className="hero">
        <HeroCanvas />
        <div className="hero-glow" aria-hidden="true" />
        <div className="hero-inner">
          <Reveal><span className="eyebrow"><span className="dot" /> Evidence-locked research · runs fully offline</span></Reveal>
          <Reveal delay={80}><h1 className="hero-title">Research that<br /><span className="grad">cites its roots.</span></h1></Reveal>
          <Reveal delay={160}>
            <p className="hero-sub">Michael writes notes in which every sentence is proven by an exact quote from a source you trust, and
              drops the ones it can't prove.</p>
          </Reveal>
          <Reveal delay={240}>
            <div className="hero-cta">
              <Magnetic><a className="cta primary" href="#ask">Ask your library</a></Magnetic>
              <Magnetic><a className="cta" href="#library">Explore topics</a></Magnetic>
            </div>
          </Reveal>
        </div>
        <a className="scroll-cue" href="#numbers" aria-label="Scroll down"><span /></a>
      </section>

      <section id="numbers" className="band">
        {[
          [<CountUp key="a" to={articles} />, "trusted articles"],
          [<CountUp key="b" to={94.4} decimals={1} suffix="%" />, "strict precision"],
          [<CountUp key="c" to={0} />, "wrong sentences accepted"],
          [<CountUp key="d" to={verified} />, "verified overview sentences"],
        ].map(([v, l], i) => (
          <Reveal key={String(l)} delay={i * 90} className="band-item">
            <div className="band-v">{v}</div><div className="band-l">{l}</div>
          </Reveal>
        ))}
      </section>

      <section className="section">
        <Reveal><h2 className="sec-title">How a sentence earns its place</h2></Reveal>
        <div className="steps">
          {STEPS.map(([n, t, d], i) => (
            <Reveal key={n} delay={i * 110} className="step">
              <span className="step-n">{n}</span><h3>{t}</h3><p>{d}</p>
            </Reveal>
          ))}
        </div>
      </section>

      <section id="ask" className="section">
        <Reveal><h2 className="sec-title">Ask what you already know</h2></Reveal>
        <Reveal delay={80}><p className="sec-sub">Instant answers from facts Michael has already proven. No model runs, so it takes milliseconds.</p></Reveal>
        <Reveal delay={140}><AskDemo /></Reveal>
      </section>

      <section id="library" className="section">
        <Reveal><h2 className="sec-title">Your library, topic by topic</h2></Reveal>
        <Reveal delay={80}><p className="sec-sub">Filter, switch views, and open any topic for its verified facts and sources.</p></Reveal>
        {subjects.length
          ? <Reveal delay={140}><Showcase subjects={subjects} /></Reveal>
          : <p className="muted">Start the backend (michael serve) to see your library.</p>}
      </section>
    </div>
  );
}
