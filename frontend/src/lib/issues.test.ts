
import { keepSelection } from "./issues";

describe("keepSelection", () => {
  it("drops a selection that is no longer in the list (e.g. after a server reset)", () => {
    const items = [{ fingerprint: "a" }, { fingerprint: "b" }];
    expect(keepSelection("a", items)).toBe("a");
    expect(keepSelection("zz", items)).toBeNull();
    expect(keepSelection(null, items)).toBeNull();
    expect(keepSelection("a", null)).toBe("a"); // list not loaded yet: keep
  });
});
