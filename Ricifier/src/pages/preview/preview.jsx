import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./preview.css";

const APPLICATIONS = [
  ["kitty", "Kitty"],
  ["i3", "i3"],
  ["polybar", "Polybar"],
  ["rofi", "Rofi"],
  ["picom", "Picom"],
];

function ConfigViewer({ result, design, onExplain, chat }) {
  const [activeApp, setActiveApp] = useState(result.files[0]?.app || "");
  const [activeLine, setActiveLine] = useState(0);
  const lineRefs = useRef([]);
  const file = result.files.find((item) => item.app === activeApp) || result.files[0];
  const lines = file?.text.split("\n") || [];

  useEffect(() => {
    setActiveLine(0);
    lineRefs.current = [];
  }, [activeApp]);

  function moveLine(event, index) {
    if (event.key === "ArrowDown" && index < lines.length - 1) {
      event.preventDefault();
      setActiveLine(index + 1);
      lineRefs.current[index + 1]?.focus();
    } else if (event.key === "ArrowUp" && index > 0) {
      event.preventDefault();
      setActiveLine(index - 1);
      lineRefs.current[index - 1]?.focus();
    } else if (event.key === "Enter" && file) {
      event.preventDefault();
      onExplain(file.app, lines[index], index + 1, design);
    }
  }

  return (
    <section className="generated-view" aria-label="Generated configuration preview">
      <div className="config-tabs" role="tablist" aria-label="Generated apps">
        {result.files.map((item) => (
          <button
            type="button"
            role="tab"
            aria-selected={item.app === activeApp}
            className={item.app === activeApp ? "active" : ""}
            key={item.app}
            onClick={() => setActiveApp(item.app)}
          >
            {item.app}
          </button>
        ))}
      </div>
      <div className="config-workspace">
        <div className="config-file">
          <div className="config-file-header">
            <span>{file?.file}</span>
            <span>↑ ↓ navigate · Enter explain</span>
          </div>
          <div className="config-lines" role="listbox" aria-label={`${activeApp} configuration`}>
            {lines.map((line, index) => (
              <button
                type="button"
                className={`config-line${index === activeLine ? " selected" : ""}`}
                key={`${index}-${line}`}
                ref={(element) => {
                  lineRefs.current[index] = element;
                }}
                autoFocus={index === 0}
                onClick={() => {
                  setActiveLine(index);
                  lineRefs.current[index]?.focus();
                }}
                onKeyDown={(event) => moveLine(event, index)}
              >
                <span className="line-number">{index + 1}</span>
                <code>{line || " "}</code>
              </button>
            ))}
          </div>
        </div>
        <aside className="parameter-chat" aria-live="polite">
          <div className="chat-heading">Ask about a parameter</div>
          <p>Select a line and press Enter to ask Gemini why it was generated.</p>
          <div className="chat-context">
            <strong>{activeApp || "config"}</strong>
            <code>{lines[activeLine] || "Select a configuration line"}</code>
          </div>
          <button
            type="button"
            className="explain-button"
            onClick={() => file && onExplain(file.app, lines[activeLine], activeLine + 1, design)}
          >
            Explain selected line
          </button>
          {chat.text && chat.app === file?.app && (
            <div className="chat-response">
              <strong>Gemma</strong>
              <p>{chat.text}</p>
              {chat.loading && <div className="chat-dots"><span /><span /><span /></div>}
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

function Preview() {
  const [selectedApps, setSelectedApps] = useState(
    APPLICATIONS.map(([id]) => id),
  );
  const [input, setInput] = useState(null);
  const [inputKind, setInputKind] = useState("image");
  const [imageUrl, setImageUrl] = useState("");
  const [imageSize, setImageSize] = useState(null);
  const [geminiConfigs, setGeminiConfigs] = useState(false);
  const [status, setStatus] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [result, setResult] = useState(null);
  const [design, setDesign] = useState({});
  const [chat, setChat] = useState({ loading: false, app: "", line: "", text: "" });

  useEffect(() => () => {
    if (imageUrl) URL.revokeObjectURL(imageUrl);
  }, [imageUrl]);

  function handleInputChange(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    const isJson = file.name.toLowerCase().endsWith(".json");
    setInput(file);
    setInputKind(isJson ? "json" : "image");
    setStatus("");
    setResult(null);
    setChat({ loading: false, app: "", line: "", text: "" });
    setImageSize(null);
    setImageUrl((currentUrl) => {
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      return isJson ? "" : URL.createObjectURL(file);
    });
  }

  function toggleApp(app) {
    setSelectedApps((current) =>
      current.includes(app)
        ? current.filter((selected) => selected !== app)
        : [...current, app],
    );
  }

  async function generate() {
    if (!input) {
      setStatus("Choose a wallpaper image or mood.json first.");
      return;
    }
    if (selectedApps.length === 0) {
      setStatus("Select at least one application.");
      return;
    }
    setIsGenerating(true);
    setStatus("Gemma is processing your design. You can keep using the window...");
    try {
      const bytes = Array.from(new Uint8Array(await input.arrayBuffer()));
      const raw = await invoke("generate_configs", {
        inputBytes: bytes,
        inputKind,
        apps: selectedApps,
        geminiConfigs,
      });
      const parsed = JSON.parse(raw);
      setResult(parsed);
      setDesign(parsed.design || {});
      setStatus(`Generated ${parsed.files.length} configuration file${parsed.files.length === 1 ? "" : "s"}.`);
    } catch (error) {
      setStatus(`Generation failed: ${error}`);
    } finally {
      setIsGenerating(false);
    }
  }

  async function explain(app, line, lineNumber, currentDesign) {
    if (!line?.trim()) return;
    setChat({ loading: true, app, line, text: "Gemma is preparing an explanation..." });
    try {
      const raw = await invoke("explain_parameter", {
        app,
        line,
        lineNumber,
        design: JSON.stringify(currentDesign),
      });
      const response = JSON.parse(raw);
      setChat({ loading: false, app, line, text: response.explanation });
    } catch (error) {
      setChat({ loading: false, app, line, text: `Explanation failed: ${error}` });
    }
  }

  return (
    <div className="preview-page">
      <div className="preview-content">
        <div className="left-panel">
          <div className="text-title">Ricify</div>
          <fieldset className="checklist-wrap">
            <legend className="check-label">Options</legend>
            <div className="check-stack" aria-label="applications to generate">
              {APPLICATIONS.map(([id, label]) => (
                <label className="check-option" key={id}>
                  <input type="checkbox" checked={selectedApps.includes(id)} onChange={() => toggleApp(id)} />
                  <span className="check-box" />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="gemini-option">
            <input type="checkbox" checked={geminiConfigs} onChange={(event) => setGeminiConfigs(event.target.checked)} />
            <span className="check-box" />
            Use Gemini for app parameters
          </label>
          <button type="button" className="submit-btn" onClick={generate} disabled={isGenerating}>
            {isGenerating ? "Processing..." : "Generate"}
          </button>
          {isGenerating && <div className="processing-indicator"><span />Gemma is working...</div>}
          {status && <pre className="generation-status">{status}</pre>}
        </div>
        <div className="right-panel">
          <label className={`image-card${input ? " has-image" : ""}${inputKind === "json" ? " json-card" : ""}`} style={imageSize ? { aspectRatio: `${imageSize.width} / ${imageSize.height}` } : undefined}>
            {inputKind === "json" && input ? (
              <>
                <span className="image-label">{input.name}</span>
                <span className="json-hint">Saved mood/design JSON</span>
              </>
            ) : imageUrl ? (
              <img className="image-preview" src={imageUrl} alt="Selected wallpaper" onLoad={(event) => setImageSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />
            ) : (
              <>
                <span className="image-label">Image insert and preview</span>
                <span className="image-plus" aria-hidden="true" />
              </>
            )}
            <input className="image-input" type="file" accept="image/*,.json,application/json" onChange={handleInputChange} />
          </label>
        </div>
      </div>
      {result && <ConfigViewer result={result} design={design} onExplain={explain} chat={chat} />}
    </div>
  );
}

export default Preview;
