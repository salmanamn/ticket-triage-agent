# Login problems in the mobile app

## Login loop or blank screen after sign-in
- Usually caused by an outdated app version or a stale session token.
- Ask the customer to update the app, then clear the app cache (Android: Settings > Apps > Pearl Pay > Storage > Clear cache; iOS: reinstall).
- Check the device date and time are set automatically; clock drift over 5 minutes breaks token validation.

## Account locked
- The account locks for 30 minutes after 5 failed password or PIN attempts.
- The customer can unlock immediately with Forgot password plus OTP verification.
- Agents must never unlock an account without verifying identity through the standard KYC questions.

## When to escalate
- Repeated lockouts the customer did not cause, or login alerts from unknown devices: escalate to Security Operations, priority critical.
- Login failing for many customers at once: raise a major incident, priority critical.