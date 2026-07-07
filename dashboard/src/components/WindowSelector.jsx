import SegmentedControl from "./SegmentedControl.jsx";

const OPTIONS = [
  { label: "1H", value: "1h" },
  { label: "6H", value: "6h" },
  { label: "24H", value: "24h" },
  { label: "7D", value: "7d" },
];

export default function WindowSelector({ value, onChange }) {
  return (
    <SegmentedControl
      options={OPTIONS}
      value={value}
      onChange={onChange}
      ariaLabel="History window"
    />
  );
}
