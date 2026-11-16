import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import HostedRoot from "./HostedRoot";
import { HOSTED } from "./api";
import "./style.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
	<React.StrictMode>
		{HOSTED ? <HostedRoot /> : <App />}
	</React.StrictMode>,
);
