// SPDX-License-Identifier: MPL-2.0
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod desktop;

fn main() {
    desktop::run();
}
