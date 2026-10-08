import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

export function NotFound() {
  return (
    <div className="space-y-3 py-10 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-sm text-muted-foreground">That address does not match anything here.</p>
      <Button asChild>
        <Link to="/">Back to the dashboard</Link>
      </Button>
    </div>
  );
}
