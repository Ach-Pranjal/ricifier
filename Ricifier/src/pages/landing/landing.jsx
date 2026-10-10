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
          <h1>Ricing<br /><em>Made Easy.</em></h1>
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
          <pre>{`[module/filesystem]
type = internal/fs
interval = 25

mount-0 = /

label-mounted = %{F#F0C674}%mountpoint%%{F-} %percentage_used%%

label-unmounted = %mountpoint% not mounted
label-unmounted-foreground = {colors.disabled}`}</pre>
          <div className="terminal-line" />
        </div>
      </section>

      <footer className="landing-footer">
        <span className="footer-line" />
        <span>Cook your Rice</span>
        <span className="footer-line" />
        <span></span>
      </footer>
    </main>
  );
}

export default Landing;
