import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { createQueryClient } from "../api/queryClient";
import { useToast } from "./toast";

/** QueryClientProvider wired to the toast system. Tests can inject their own client. */
export function QueryProvider({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const { toast } = useToast();
  const [queryClient] = useState(() => client ?? createQueryClient(toast));
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
