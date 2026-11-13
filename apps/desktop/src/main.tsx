// SPDX-License-Identifier: MPL-2.0
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./style.css";

const element = document.getElementById("root");
if (!element) throw new Error("Corinthos root element is missing.");
createRoot(element).render(<App />);
