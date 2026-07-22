(function () {
  const config = window.ChatListSiteConfig || {};
  const version = config.version || "1.0.0";
  const releaseTag = config.releaseTag || `v${version}`;
  const repositoryUrl = config.repositoryUrl || "https://github.com/ARB774/ChatList";
  const releaseUrl = `${repositoryUrl}/releases/tag/${releaseTag}`;
  const installerUrl = `${repositoryUrl}/releases/download/${releaseTag}/ChatListApp_Setup_${version}.exe`;

  document.title = `${config.appName || "ChatList"} ${version}`;

  const setText = (selector, value) => {
    document.querySelectorAll(selector).forEach((node) => {
      node.textContent = value;
    });
  };

  const setHref = (selector, href) => {
    document.querySelectorAll(selector).forEach((node) => {
      node.setAttribute("href", href);
    });
  };

  setText("#app-version", version);
  setText("#footer-version", version);
  setText("[data-version-inline]", version);

  setHref("#download-installer", installerUrl);
  setHref("#open-release", releaseUrl);
  setHref("#footer-release-link", releaseUrl);
  setHref("#open-repo", repositoryUrl);
})();

