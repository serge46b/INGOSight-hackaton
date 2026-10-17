import { NavLink, Outlet } from "react-router-dom";

export function Shell() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">MAIL-AGENT</div>
        <nav className="nav" aria-label="Разделы">
          <NavLink to="/" end>
            Список тредов
          </NavLink>
          <NavLink to="/digest">Сводка</NavLink>
          <NavLink to="/settings">Настройки</NavLink>
        </nav>
      </header>
      <Outlet />
    </div>
  );
}
