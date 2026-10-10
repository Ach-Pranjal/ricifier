import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./preview.css";

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
  return (
    <div className="main">
        <div className="left">
            <div className = "left-top">
                <h1>Welcome to Ricifier.</h1>
            </div>
            <div className = "left-bottom">
                <form className="row" onSubmit={(e) => { e.preventDefault(); runPython(); }}>
                    <input
                        id="greet-input"
                        onChange={(e) => setName(e.currentTarget.value)}
                        placeholder="Enter a name..."
                    />
                    <button type="submit">Greet</button>
                </form>
            </div>
        </div>
        <div className="right">
            <p>{greetMsg}</p>            
        </div>
    </div>
  )
};

export default Preview;
