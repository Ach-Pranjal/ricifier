import "./selection.css";
import textContent from "./test.txt?raw";

function Selection() {
  return (
    <main className="selection-page">
      <section className="text-preview" aria-label="Text file preview">
        <div className="preview-header">
          <span>Config file Preview</span>
          <span className="file-name">Config</span>
        </div>
        <pre className="text-content">{textContent}</pre>
      </section>

      <footer className="selection-actions">
        <button
          type="button"
          className="selection-button secondary"
          onClick={() => window.history.back()}
        >
          Back
        </button>
        <button type="button" className="selection-button primary">
          Done
        </button>
      </footer>
    </main>
  );
}

export default Selection;
