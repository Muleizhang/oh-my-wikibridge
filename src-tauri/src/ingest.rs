use calamine::{DataType, Reader, open_workbook_auto};
use roxmltree::Document;
use scraper::{Html, Selector};
use serde::{Deserialize, Serialize};
use std::{fs, io::Read, path::Path};
use zip::ZipArchive;

pub const MAX_TEXT_BYTES: usize = 32 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Unit {
    pub kind: String,
    pub ordinal: u32,
    pub locator: String,
    pub text: String,
    pub method: String,
    pub confidence: Option<f32>,
}

fn unit(kind: &str, ordinal: u32, locator: String, text: String) -> Unit {
    Unit {
        kind: kind.into(),
        ordinal,
        locator,
        text: text.trim().into(),
        method: "native".into(),
        confidence: None,
    }
}

pub fn needs_browser(extension: &str) -> bool {
    matches!(
        extension,
        "pdf" | "png" | "jpg" | "jpeg" | "webp" | "bmp" | "tif" | "tiff"
    )
}

pub fn supported(extension: &str) -> bool {
    needs_browser(extension)
        || matches!(
            extension,
            "txt"
                | "md"
                | "markdown"
                | "html"
                | "htm"
                | "csv"
                | "tsv"
                | "json"
                | "jsonl"
                | "xml"
                | "yaml"
                | "yml"
                | "log"
                | "srt"
                | "vtt"
                | "docx"
                | "pptx"
                | "xlsx"
                | "xls"
                | "xlsb"
                | "ods"
                | "odt"
                | "odp"
                | "epub"
        )
}

pub fn extract(path: &Path, extension: &str) -> Result<Vec<Unit>, String> {
    let units = match extension {
        "docx" | "pptx" | "odt" | "odp" | "epub" => office(path, extension)?,
        "xlsx" | "xls" | "xlsb" | "ods" => sheets(path)?,
        "csv" | "tsv" => rows(path, if extension == "tsv" { b'\t' } else { b',' })?,
        "html" | "htm" => {
            let text = read_text(path)?;
            vec![unit("section", 1, "网页正文".into(), html_text(&text))]
        }
        _ => {
            let text = read_text(path)?;
            text.split_inclusive('\n')
                .enumerate()
                .filter(|(_, line)| !line.trim().is_empty())
                .map(|(index, line)| {
                    unit(
                        "line",
                        index as u32 + 1,
                        format!("第 {} 行", index + 1),
                        line.into(),
                    )
                })
                .collect()
        }
    };
    if units.iter().all(|unit| unit.text.is_empty()) {
        return Err("没有提取到可检索文本。请检查文件内容。".into());
    }
    Ok(units)
}

fn read_text(path: &Path) -> Result<String, String> {
    let file = fs::File::open(path).map_err(|error| error.to_string())?;
    let mut bytes = Vec::new();
    file.take((MAX_TEXT_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.len() > MAX_TEXT_BYTES {
        return Err("文本格式的单文件解析上限为 32 MiB。".into());
    }
    if bytes.starts_with(&[0xff, 0xfe]) || bytes.starts_with(&[0xfe, 0xff]) {
        if !bytes.len().is_multiple_of(2) {
            return Err("UTF-16 文件含有不完整的字符。".into());
        }
        let little_endian = bytes[0] == 0xff;
        let words: Vec<u16> = bytes[2..]
            .chunks_exact(2)
            .map(|word| {
                if little_endian {
                    u16::from_le_bytes([word[0], word[1]])
                } else {
                    u16::from_be_bytes([word[0], word[1]])
                }
            })
            .collect();
        return String::from_utf16(&words).map_err(|_| "无法解码 UTF-16 文本。".into());
    }
    String::from_utf8(
        bytes
            .strip_prefix(&[0xef, 0xbb, 0xbf])
            .unwrap_or(&bytes)
            .to_vec(),
    )
    .map_err(|_| "请将文本另存为 UTF-8 或带 BOM 的 UTF-16。".into())
}

fn html_text(source: &str) -> String {
    let html = Html::parse_document(source);
    let body = Selector::parse("body").expect("static selector");
    html.select(&body)
        .flat_map(|element| element.descendants())
        .filter_map(|node| {
            let text = node.value().as_text()?;
            if node.ancestors().any(|ancestor| {
                ancestor.value().as_element().is_some_and(|element| {
                    matches!(element.name(), "style" | "script" | "noscript" | "template")
                })
            }) {
                return None;
            }
            Some(text.trim().to_owned())
        })
        .filter(|text| !text.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

fn archive_text(archive: &mut ZipArchive<fs::File>, name: &str) -> Result<String, String> {
    let entry = archive.by_name(name).map_err(|error| error.to_string())?;
    if entry.size() > MAX_TEXT_BYTES as u64 {
        return Err(format!("压缩文档内的 {name} 超过解析上限。"));
    }
    let mut text = String::new();
    entry
        .take((MAX_TEXT_BYTES + 1) as u64)
        .read_to_string(&mut text)
        .map_err(|error| error.to_string())?;
    if text.len() > MAX_TEXT_BYTES {
        return Err(format!("压缩文档内的 {name} 超过解析上限。"));
    }
    Ok(text)
}

fn xml_node_text(node: roxmltree::Node<'_, '_>) -> String {
    node.descendants()
        .filter(|child| {
            child.is_text()
                && child
                    .parent()
                    .is_some_and(|parent| parent.has_tag_name("t"))
        })
        .filter_map(|child| child.text())
        .collect()
}

fn office(path: &Path, extension: &str) -> Result<Vec<Unit>, String> {
    let mut archive = ZipArchive::new(fs::File::open(path).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())?;
    match extension {
        "docx" => {
            let xml = archive_text(&mut archive, "word/document.xml")?;
            let document = Document::parse(&xml).map_err(|error| error.to_string())?;
            Ok(document
                .descendants()
                .filter(|node| {
                    node.has_tag_name((
                        "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                        "p",
                    )) || node
                        .has_tag_name(("http://purl.oclc.org/ooxml/wordprocessingml/main", "p"))
                })
                .enumerate()
                .map(|(index, node)| {
                    unit(
                        "paragraph",
                        index as u32 + 1,
                        format!("第 {} 段", index + 1),
                        xml_node_text(node),
                    )
                })
                .collect())
        }
        "pptx" => {
            let mut slides: Vec<_> = archive
                .file_names()
                .filter_map(|name| {
                    let ordinal = name
                        .strip_prefix("ppt/slides/slide")?
                        .strip_suffix(".xml")?
                        .parse::<u32>()
                        .ok()?;
                    Some((ordinal, name.to_owned()))
                })
                .collect();
            // The presentation manifest defines slideshow order after slides have been reordered.
            if let (Ok(manifest), Ok(relationships)) = (
                archive_text(&mut archive, "ppt/presentation.xml"),
                archive_text(&mut archive, "ppt/_rels/presentation.xml.rels"),
            ) {
                if let (Ok(manifest), Ok(relationships)) =
                    (Document::parse(&manifest), Document::parse(&relationships))
                {
                    let ordered: Vec<_> = manifest
                        .descendants()
                        .filter(|node| node.has_tag_name("sldId"))
                        .filter_map(|node| {
                            let id = node
                                .attributes()
                                .find(|attribute| {
                                    attribute.name() == "id" && attribute.namespace().is_some()
                                })?
                                .value();
                            let target = relationships
                                .descendants()
                                .find(|rel| rel.attribute("Id") == Some(id))?
                                .attribute("Target")?;
                            let path = if target.starts_with('/') {
                                target.trim_start_matches('/').to_owned()
                            } else {
                                format!("ppt/{target}")
                            };
                            slides
                                .iter()
                                .find(|(_, name)| *name == path)
                                .map(|(_, name)| name.clone())
                        })
                        .collect();
                    if ordered.len() == slides.len() && !ordered.is_empty() {
                        slides = ordered
                            .into_iter()
                            .enumerate()
                            .map(|(index, path)| (index as u32 + 1, path))
                            .collect();
                    }
                }
            }
            slides.sort_by_key(|(ordinal, _)| *ordinal);
            let mut units = Vec::new();
            for (ordinal, name) in slides {
                let xml = archive_text(&mut archive, &name)?;
                let document = Document::parse(&xml).map_err(|error| error.to_string())?;
                let text = document
                    .descendants()
                    .filter(|node| node.has_tag_name("p"))
                    .map(xml_node_text)
                    .filter(|text| !text.is_empty())
                    .collect::<Vec<_>>()
                    .join("\n");
                units.push(unit(
                    "slide",
                    ordinal,
                    format!("第 {ordinal} 张幻灯片"),
                    text,
                ));
            }
            Ok(units)
        }
        "odt" | "odp" => {
            let xml = archive_text(&mut archive, "content.xml")?;
            let document = Document::parse(&xml).map_err(|error| error.to_string())?;
            let names: &[&str] = if extension == "odt" {
                &["h", "p"]
            } else {
                &["page"]
            };
            Ok(document
                .descendants()
                .filter(|node| node.is_element() && names.contains(&node.tag_name().name()))
                .enumerate()
                .map(|(index, node)| {
                    let text = node
                        .descendants()
                        .filter(|child| child.is_text())
                        .filter_map(|child| child.text())
                        .map(str::trim)
                        .filter(|text| !text.is_empty())
                        .collect::<Vec<_>>()
                        .join(" ");
                    let (kind, label) = if extension == "odt" {
                        ("paragraph", "段")
                    } else {
                        ("slide", "张幻灯片")
                    };
                    unit(
                        kind,
                        index as u32 + 1,
                        format!("第 {} {label}", index + 1),
                        text,
                    )
                })
                .collect())
        }
        _ => {
            let mut names: Vec<_> = archive
                .file_names()
                .filter(|name| name.ends_with(".xhtml") || name.ends_with(".html"))
                .map(str::to_owned)
                .collect();
            names.sort();
            names
                .into_iter()
                .enumerate()
                .map(|(index, name)| {
                    let html = archive_text(&mut archive, &name)?;
                    Ok(unit("section", index as u32 + 1, name, html_text(&html)))
                })
                .collect()
        }
    }
}

fn column_name(mut number: usize) -> String {
    let mut name = String::new();
    loop {
        name.insert(0, (b'A' + (number % 26) as u8) as char);
        if number < 26 {
            return name;
        }
        number = number / 26 - 1;
    }
}

fn sheets(path: &Path) -> Result<Vec<Unit>, String> {
    let mut book = open_workbook_auto(path).map_err(|error| error.to_string())?;
    let mut units = Vec::new();
    for sheet in book.sheet_names() {
        let range = book
            .worksheet_range(&sheet)
            .map_err(|error| error.to_string())?;
        let Some((first_row, first_column)) = range.start() else {
            continue;
        };
        for (row_index, row) in range.rows().enumerate() {
            let row_number = first_row as usize + row_index + 1;
            let cells: Vec<_> = row
                .iter()
                .enumerate()
                .filter(|(_, cell)| !cell.is_empty())
                .map(|(index, cell)| {
                    format!(
                        "{}{}: {cell}",
                        column_name(first_column as usize + index),
                        row_number
                    )
                })
                .collect();
            if !cells.is_empty() {
                units.push(unit(
                    "row",
                    units.len() as u32 + 1,
                    format!("{sheet} · 第 {row_number} 行"),
                    cells.join(" | "),
                ));
            }
        }
    }
    Ok(units)
}

fn rows(path: &Path, delimiter: u8) -> Result<Vec<Unit>, String> {
    let text = read_text(path)?;
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(false)
        .flexible(true)
        .delimiter(delimiter)
        .from_reader(text.as_bytes());
    reader
        .records()
        .enumerate()
        .map(|(index, row)| {
            let row = row.map_err(|error| error.to_string())?;
            let cells = row
                .iter()
                .enumerate()
                .filter(|(_, cell)| !cell.is_empty())
                .map(|(column, cell)| format!("{}{}: {cell}", column_name(column), index + 1))
                .collect::<Vec<_>>();
            let line = row
                .position()
                .map_or(index as u64 + 1, |position| position.line());
            Ok(unit(
                "row",
                index as u32 + 1,
                format!("第 {} 条记录 · 第 {line} 行", index + 1),
                cells.join(" | "),
            ))
        })
        .collect()
}
