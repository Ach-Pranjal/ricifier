import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./preview.css";
import { Link } from "react-router-dom";

function Preview() {
    const [greetMsg, setGreetMsg] = useState("");
    const [name, setName] = useState("");

    async function greet() {
        setGreetMsg(await invoke("greet", { name }));
    }

    async function runPython() {
        try {
        const result = await invoke("run_python", { name });
        setGreetMsg(result);
        } catch (error) {
        setGreetMsg(`Error: ${error}`);
        }
    }
  const [imageUrl, setImageUrl] = useState("");
  const [imageSize, setImageSize] = useState(null);

  useEffect(() => {
    return () => {
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
    };
  }, [imageUrl]);

  function handleImageChange(event) {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    setImageUrl((currentUrl) => {
      if (currentUrl) {
        URL.revokeObjectURL(currentUrl);
      }
      return URL.createObjectURL(file);
    });
    setImageSize(null);
  }

  return (
    <div className="preview-page">
      <div className="preview-content">
        <div className="left-panel">
          <div className="text-title">Ricify</div>

          <fieldset className="checklist-wrap">
            <legend className="check-label">Options</legend>
            <div className="check-stack" aria-label="checkboxes">
              <label className="check-option">
                <input type="checkbox" name="options" value="option1" />
                <span className="check-box" />
                Kitty
              </label>
              <label className="check-option">
                <input type="checkbox" name="options" value="option2" />
                <span className="check-box" />
                i3
              </label>
              <label className="check-option">
                <input type="checkbox" name="options" value="option3" />
                <span className="check-box" />
                Polybar
              </label>
              <label className="check-option">
                <input type="checkbox" name="options" value="option4" />
                <span className="check-box" />
                Rofi
              </label>
              <label className="check-option">
                <input type="checkbox" name="options" value="option5" />
                <span className="check-box" />
                Picom
              </label>
            </div>
          </fieldset>
            <Link to="/selection">
          <button type="button" className="submit-btn">
            Next
          </button>
          </Link>
        </div>

        <div className="right-panel">
          <label
            className={`image-card${imageUrl ? " has-image" : ""}`}
            style={imageSize ? { aspectRatio: `${imageSize.width} / ${imageSize.height}` } : undefined}
          >
            {imageUrl ? (
              <img
                className="image-preview"
                src={imageUrl}
                alt="Selected preview"
                onLoad={(event) => {
                  setImageSize({
                    width: event.currentTarget.naturalWidth,
                    height: event.currentTarget.naturalHeight,
                  });
                }}
              />
            ) : (
              <>
                <span className="image-label">Image insert and preview</span>
                <span className="image-plus" aria-hidden="true" />
              </>
            )}
            <input
              className="image-input"
              type="file"
              accept="image/*"
              onChange={handleImageChange}
            />
          </label>
        </div>
      </div>
    </div>
  );
}

export default Preview;
