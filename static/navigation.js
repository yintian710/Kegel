"use strict";

(() => {
  const header = document.querySelector("[data-site-navigation]");
  const pages = [
    { path: "/", label: "首页" },
    { path: "/practice", label: "提肛练习" },
    { path: "/shop", label: "商店" },
    { path: "/donate", label: "赞助" },
    { path: "/admin", label: "管理" },
  ];
  const pathname = location.pathname.replace(/\.html$/, "");
  const currentPath = pathname === "/index" ? "/" : pathname;
  let account = null;

  header.innerHTML = `
    <a class="site-brand" href="/" data-interactive>
      <img class="brand-logo" src="/img/icon-48.png" alt="提肛打卡 Logo" />
      <span>提肛打卡</span><span class="brand-badge">DAILY</span>
    </a>
    <nav class="site-nav" aria-label="主导航" data-interactive></nav>`;

  const nav = header.querySelector("nav");
  for (const page of pages) {
    const link = document.createElement("a");
    link.className = "nav-link";
    link.href = page.path;
    link.textContent = page.label;
    if (page.path === currentPath) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
    nav.append(link);
  }

  const accountButton = document.createElement("button");
  accountButton.id = "accountButton";
  accountButton.className = "user-btn";
  accountButton.type = "button";
  accountButton.disabled = true;
  accountButton.textContent = "正在加载账户…";
  nav.append(accountButton);

  function update(data) {
    if (!data || !Object.hasOwn(data, "user")) return;
    account = data;
    accountButton.textContent = data.user ? `@${data.user.username} · 退出`
      : data.oauth_ready ? "LINUX DO 登录" : "登录暂未配置";
    accountButton.disabled = !data.user && !data.oauth_ready;
  }

  function login() {
    if (!account?.oauth_ready) return;
    window.location.assign(`/auth/linuxdo/start?${new URLSearchParams({ next: currentPath })}`);
  }

  accountButton.addEventListener("click", () => {
    if (account?.user) window.location.assign("/auth/logout");
    else login();
  });

  window.SiteNavigation = Object.freeze({ update, login });
})();
