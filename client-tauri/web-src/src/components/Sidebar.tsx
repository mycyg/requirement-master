import { useSpace } from "@yqgl/shared";
import { SidebarWork } from "@/components/SidebarWork";
import { SidebarDispatch } from "@/components/SidebarDispatch";

/**
 * Dispatcher — picks the right sidebar for the active Space. The View
 * Transitions API (triggered by `useSpace` on switch) crossfades the two
 * trees together, so we don't need any animation logic here.
 */
export function Sidebar() {
  const { space } = useSpace();
  return space === "dispatch" ? <SidebarDispatch /> : <SidebarWork />;
}
