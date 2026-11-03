import { AppShell } from "@/components/app-shell";

export default function DashLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
