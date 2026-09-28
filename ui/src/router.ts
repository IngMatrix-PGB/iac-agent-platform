export type Route =
  | { name: "compose" }
  | { name: "request"; requestId: string }
  | { name: "unknown" };

export function parseRoute(pathname: string): Route {
  if (pathname === "/") {
    return { name: "compose" };
  }
  const match = /^\/requests\/([^/]+)$/.exec(pathname);
  const segment = match?.[1];
  if (segment) {
    return { name: "request", requestId: decodeURIComponent(segment) };
  }
  return { name: "unknown" };
}
