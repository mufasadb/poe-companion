# ZMK: PoE selector layer

Goes in the **separate firmware repo** `mufasadb/wireless-keyboard`, file `config/sofle.keymap`.
Your existing layers are indexed by order: `default(0) raise(1) linux_default(2) lower(3)
linux_raised(4) config(5)`. We add **`poe_layer` as index 6**.

Contract (matches `app/config.json`):

| Gesture (on PoE layer only) | Sends | App action |
|---|---|---|
| Right encoder CW  | `F14` | next |
| Right encoder CCW | `F13` | prev |
| Select thumb key  | `F15` | type selected regex |
| Gem-done thumb key| `F16` | mark next gem done |

Normal use is untouched — the encoder stays **volume** ("home") until you toggle this layer on.

## 1. Add the layer

Paste as the **last layer inside `keymap { … }`**, right after `config_layer { … }`:

```dts
        poe_layer {
            display-name = "poe";
            // Left encoder stays volume; RIGHT encoder becomes prev/next.
            //   &inc_dec_kp <on-CW> <on-CCW>  → CW = next (F14), CCW = prev (F13)
            bindings = <
&tog 6  &trans  &trans  &trans  &trans  &trans                    &trans  &trans  &trans  &trans  &trans  &trans
&trans  &trans  &trans  &trans  &trans  &trans                    &trans  &trans  &trans  &trans  &trans  &trans
&trans  &trans  &trans  &trans  &trans  &trans                    &trans  &trans  &trans  &trans  &trans  &trans
&trans  &trans  &trans  &trans  &trans  &trans  &trans    &trans  &trans  &trans  &trans  &trans  &trans  &trans
                &trans  &trans  &kp F16 &kp F15 &trans    &trans  &kp F15 &kp F16 &trans  &trans
            >;

            sensor-bindings =
                <&inc_dec_kp C_VOL_UP C_VOL_DN>,   // left encoder: volume (unchanged)
                <&inc_dec_kp F14 F13>;             // right encoder: next / prev
        };
```

- `&tog 6` (top-left) toggles the PoE layer **off** again.
- `&kp F15` = **select/type**, `&kp F16` = **gem done**, placed on the inner thumb keys of
  *both* halves so it's reachable whichever hand is free. Move them to taste.

## 2. Add a way IN to the layer

Put a `&tog 6` on a free `&trans` in `raise_layer` (reached by holding your RAISE thumb).
E.g. swap the `&trans` next to the existing `&tog 2` on the top row:

```
&tog 5  &tog 2  &tog 6  &trans  &trans  &trans   …
```

Flow in-game: hold RAISE → tap that key → release → you're in PoE mode (encoder = scroll).
Tap `&tog 6` (top-left of the PoE layer) to leave.

## 3. Build & flash

Commit + push → GitHub **Actions** builds two `.uf2`. Double-tap reset on each half
(`NICENANO` drive appears) and drag the matching file on. Flash **both** halves.

## Verify

`python app/poe_selector.py --watch`, toggle the PoE layer, turn the knob →
you should see `KEY_F14` / `KEY_F13` (down), and the thumb keys `KEY_F15` / `KEY_F16`.

## Note on the encoder push

If your right encoder's *push* switch is wired in the shield matrix, we can move `select`
(`F15`) onto it instead of a thumb key — confirm by running `--watch` and pressing the knob
to see whether it emits anything.
