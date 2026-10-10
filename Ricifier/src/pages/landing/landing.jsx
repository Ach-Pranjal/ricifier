import { useState } from "react";
import { Link } from "react-router-dom";
import "./landing.css";

function Landing() {
  return (
    <main className="container">
        <div className="button">
            <Link to="/preview">
                <button type="submit"><h1>Get Started</h1></button>
            </Link>
        </div>
    </main>
  )
};

export default Landing;
