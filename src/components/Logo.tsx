/** GenFlows brand mark — the official agency logo image. */
export function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <img
      src="/genflows_agency_logo.jpg"
      width={size}
      height={size}
      alt="GenFlows"
      className="logo-mark"
      draggable={false}
    />
  )
}
