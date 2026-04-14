// static/admin/js/sidebar-collapse.js
document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.querySelector(".unfold-sidebar");
    if (!sidebar) return;

    const toggle = document.createElement("button");
    toggle.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h7" /></svg>`;
    toggle.className = "unfold-sidebar-toggle p-2 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300";
    toggle.style.position = "absolute";
    toggle.style.top = "20px";
    toggle.style.right = "12px";

    toggle.addEventListener("click", () => {
        const isCollapsed = sidebar.classList.toggle("unfold-sidebar-collapsed");
        localStorage.setItem("sidebar-collapsed", isCollapsed);
    });

    sidebar.appendChild(toggle);

    // Restore state
    if (localStorage.getItem("sidebar-collapsed") === "true") {
        sidebar.classList.add("unfold-sidebar-collapsed");
    }
});