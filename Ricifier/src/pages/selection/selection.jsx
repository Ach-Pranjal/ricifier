import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./selection.css";

function Selection() {
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

    <main className="container">
      <h1>Welcome to Ricifier</h1>

      <div className="row">
      </div>
      <p>Enter Your Name</p>

      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          runPython();
        }}
      >
        <input
          id="greet-input"
          onChange={(e) => setName(e.currentTarget.value)}
          placeholder="Enter a name..."
        />
        <button type="submit">Greet</button>
      </form>
      <p>{greetMsg}</p>
    </main>
  )
};

export default Selection;
