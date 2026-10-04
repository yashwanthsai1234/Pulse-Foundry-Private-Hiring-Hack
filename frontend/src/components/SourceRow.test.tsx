import { render, screen } from "@testing-library/react";
import { SourceRow } from "./SourceRow";

describe("SourceRow", () => {
  it("renders the raw row and highlights only the loc.col cell", () => {
    render(<SourceRow raw={{ name: "Ann", license_no: "RN-1", note: null }} col="license_no" row={7} />);
    expect(screen.getByText("RN-1")).toHaveAttribute("data-highlight", "true");
    expect(screen.getByText("Ann")).not.toHaveAttribute("data-highlight");
    expect(screen.getByText("row 7")).toBeInTheDocument();
  });
});
