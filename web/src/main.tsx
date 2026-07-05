import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { connect } from "./ws";
import "./styles.css";

connect(); // module-scope: one socket for the tab's lifetime, before React mounts
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
