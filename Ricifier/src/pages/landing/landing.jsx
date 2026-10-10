import { Link } from "react-router-dom";
import "./landing.css";

function Landing() {
  return (
    <main className="landing-page">
      <nav className="landing-nav" aria-label="Main navigation">
        <span className="brand">ricifier<span className="brand-mark">.</span></span>
        <span className="nav-caption">linux desktop customization</span>
      </nav>

      <section className="landing-hero">
        <div className="hero-copy">
          <p className="eyebrow">01 / make it yours</p>
          <h1>Rice your<br /><em>Linux.</em></h1>
          <p className="hero-description">
            Build a desktop that feels like home. Choose your setup,
            preview your files, and shape every detail of your environment.
          </p>
          <Link className="start-link" to="/preview">
            <span>Get started</span>
            <span className="arrow" aria-hidden="true">-&gt;</span>
          </Link>
        </div>

        <div className="terminal-card" aria-label="Example Linux configuration">
          <div className="terminal-bar">
            <span className="terminal-dot" />
            <span className="terminal-dot" />
            <span className="terminal-dot" />
            <span className="terminal-title">~ / .config</span>
          </div>
          <pre>{`$ ricifier init

  selecting a style...
  [ok] minimal
  [ok] monochrome
  [ok] yours

  ready when you are_`}</pre>
          <div className="terminal-line" />
        </div>
      </section>

      <footer className="landing-footer">
        <span>your workflow / your rules</span>
        <span className="footer-line" />
        <span>v 0.1</span>
      </footer>
    </main>
  );
}

export default Landing;
