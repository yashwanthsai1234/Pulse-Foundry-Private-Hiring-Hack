import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "../App";

const renderAt = (path: string) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);

describe("pages in mock mode", () => {
  it("header shows live CRITICAL/HIGH counts", async () => {
    renderAt("/ingest");
    await waitFor(() => expect(screen.getByTestId("critical-count")).toHaveTextContent("CRITICAL 2"));
    expect(screen.getByTestId("high-count")).toHaveTextContent("HIGH 1");
  });

  it("Ingest: dropping files streams the pipeline feed", async () => {
    renderAt("/ingest");
    await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "hr_roster.csv"));
    expect(await screen.findByText("hr_roster.csv", {}, { timeout: 2000 })).toBeInTheDocument();
    expect(await screen.findByText("employee_id → person.employee_id", {}, { timeout: 3000 })).toBeInTheDocument();
  });

  it("Issues: lists by severity, shows evidence with PDF highlight, updates status", async () => {
    renderAt("/issues");
    await userEvent.click(await screen.findByText(/Marcus Bell worked 4 shifts/));
    expect(await screen.findByTestId("highlight")).toBeInTheDocument();
    expect(screen.getByText("✓ golden")).toBeInTheDocument();
    expect(screen.getByText("✗ not golden")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(screen.getAllByText("acknowledged").length).toBeGreaterThan(0));
  });

  it("People: table and drawer", async () => {
    renderAt("/people");
    await userEvent.click(await screen.findByText("Marcus Bell"));
    const drawer = await screen.findByLabelText("person detail");
    expect(await within(drawer).findByText("conflict")).toBeInTheDocument();
  });

  it("Shifts: red cells for invalid licenses and RN coverage row", async () => {
    renderAt("/shifts");
    expect(await screen.findAllByTestId("invalid-cell")).toHaveLength(4);
    expect(screen.getAllByText("RN coverage (h)")).toHaveLength(2);
  });

  it("Credentials: buckets", async () => {
    renderAt("/credentials");
    expect(await screen.findByText("Overdue (1)")).toBeInTheDocument();
    expect(screen.getByText("Within 60 days (1)")).toBeInTheDocument();
  });

  it("Exports: PBJ preview with status filter", async () => {
    renderAt("/exports");
    expect(await screen.findByText("9 of 9 rows")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("status"), "ready");
    expect(screen.getByText("4 of 9 rows")).toBeInTheDocument();
  });

  it("Contracts: approve", async () => {
    renderAt("/contracts");
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument());
  });

  it("unknown deep link shows a not-found page, not a blank screen", () => {
    renderAt("/nope/zzz");
    expect(screen.getByText(/Page not found/)).toBeInTheDocument();
  });
});
