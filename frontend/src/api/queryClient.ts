import { QueryClient } from "@tanstack/react-query";
import { isRetryable } from "./errors";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: false,
        // retry transient failures (network, 5xx) twice; never retry 4xx
        retry: (count, error) => count < 2 && isRetryable(error),
      },
    },
  });
}
