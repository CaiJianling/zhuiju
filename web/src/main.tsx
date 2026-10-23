import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

const host = document.getElementById("app");

/* 「详情从海报长出来」这件事浏览器支不支持，CSS 也要知道一份：
   支持的时候抽屉不再自己滑一遍（两个动画叠着看就是整块在抖），只留那张图缩放。
   偏好减少动效的人那边由 App 里的 vtOn 挡掉缩放，这里的类名不影响那条。 */
if ("startViewTransition" in document) document.documentElement.classList.add("vt-ok");

if (host) {
  createRoot(host).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
