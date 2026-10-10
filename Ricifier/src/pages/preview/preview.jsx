import { useEffect, useState } from "react";
import "./preview.css";

function Preview() {
  const [imageUrl, setImageUrl] = useState("");

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
                Option 1
                <span className="check-box" />
              </label>
              <label className="check-option">
                <input type="checkbox" name="options" value="option2" />
                Option 1
                <span className="check-box" />
              </label>
              <label className="check-option">
                <input type="checkbox" name="options" value="option3" />
                Option 1
                <span className="check-box" />
              </label>
              <label className="check-option">
                <input type="checkbox" name="options" value="option4" />
                Option 1
                <span className="check-box" />
              </label>
              <label className="check-option">
                <input type="checkbox" name="options" value="option5" />
                Option 1
                <span className="check-box" />
              </label>
            </div>
          </fieldset>

          <button type="button" className="submit-btn">
            Next
          </button>
        </div>

        <div className="right-panel">
          <label className={`image-card${imageUrl ? " has-image" : ""}`}>
            {imageUrl ? (
              <img className="image-preview" src={imageUrl} alt="Selected preview" />
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
