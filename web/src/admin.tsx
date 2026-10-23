import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import AdminApp from "./admin/AdminApp";
import "./styles.css";

interface Boot {
  authed: boolean;
  route: string;
  first?: boolean;
  min_len?: number;
  env_lock?: boolean;
  temp?: boolean;
}

const el = document.getElementById("boot-data");
let boot: Boot = { authed: false, route: "/admin" };
try {
  boot = { ...boot, ...(JSON.parse(el?.textContent || "{}") as Boot) };
} catch {
  /* 解析不了就按"没登录"处理，界面上会弹口令框，比白屏强 */
}

const host = document.getElementById("app");
if (host) {
  createRoot(host).render(
    <StrictMode>
      <AdminApp boot={boot} />
    </StrictMode>,
  );
}
