"""
Bella+Canvas spec sheet data extracted from official PDFs.
Styles: 3413, 3413Y, 3501, 3501CVC, 3501Y, 3501YCVC, 3513, 3513Y, 3719, 3719Y, 3729, 3901, 3901Y, 3945, 4711, 4719, 6400
"""

BELLA_CANVAS_SPECS = {
    '3413': {
        'style_number': '3413',
        'description': 'The Bella+Canvas 3413 Triblend Tee combines polyester, cotton, and rayon for a soft, broken-in feel. This unisex short sleeve tee features a relaxed fit with exceptional drape and comfort. Side-seamed construction with shoulder-to-shoulder taping for durability. Perfect for everyday wear with a vintage-inspired look.',
        'fabric': '50% polyester, 25% combed and ring-spun cotton, 25% rayon',
        'fit_guide': 'Unisex sizing, relaxed fit, side-seamed',
        'size_chart': {
            'XS': {'chest': '16.5', 'length': '27'},
            'S': {'chest': '18', 'length': '28'},
            'M': {'chest': '20', 'length': '29'},
            'L': {'chest': '22', 'length': '30'},
            'XL': {'chest': '24', 'length': '31'},
            '2XL': {'chest': '26', 'length': '32'},
            '3XL': {'chest': '28', 'length': '33'},
            '4XL': {'chest': '30', 'length': '34'}
        }
    },
    '3413Y': {
        'style_number': '3413Y',
        'description': 'The youth version of the popular 3413 Triblend Tee. Same soft tri-blend fabric (polyester, cotton, rayon) sized and fitted for kids. Features side-seamed construction for durability. Perfect for youth programs, schools, and sports teams.',
        'fabric': '50% polyester, 25% combed and ring-spun cotton, 25% rayon',
        'fit_guide': 'Youth sizing, relaxed fit, side-seamed',
        'size_chart': {
            'YS': {'chest': '15.25', 'length': '20.875'},
            'YM': {'chest': '16.25', 'length': '22.125'},
            'YL': {'chest': '17.25', 'length': '23.375'},
            'YXL': {'chest': '18.25', 'length': '24.375'}
        }
    },
    '3501': {
        'style_number': '3501',
        'description': 'The Bella+Canvas 3501 is the essential unisex jersey long sleeve tee. Made from Airlume combed and ring-spun cotton (various blends available for heather colors), this classic tee offers exceptional softness and durability. Features side-seamed construction, shoulder-to-shoulder taping, and a retail fit. Perfect for cooler weather or layered looks.',
        'fabric': 'Multiple options: 30/1 100% Airlume combed and ring-spun cotton; 32/1 99% cotton 1% polyester; 32/1 52% cotton 48% polyester; 32/1 90% cotton 10% polyester; 40/1 50% polyester 25% cotton 25% rayon; 30/1 50% polyester 37.5% cotton 12.5% rayon; 30/1 40% polyester 30% cotton 30% rayon',
        'fit_guide': 'Unisex sizing, retail fit, side-seamed',
        'size_chart': {
            'XS': {'chest': '16.5', 'length': '28'},
            'S': {'chest': '18', 'length': '29'},
            'M': {'chest': '20', 'length': '30'},
            'L': {'chest': '22', 'length': '31'},
            'XL': {'chest': '24', 'length': '32'},
            '2XL': {'chest': '26', 'length': '33'},
            '3XL': {'chest': '28', 'length': '33'},
            '4XL': {'chest': '30', 'length': '34'}
        }
    },
    '3501CVC': {
        'style_number': '3501CVC',
        'description': 'The Bella+Canvas 3501CVC Unisex Heather CVC Long Sleeve Tee combines the comfort of cotton with polyester for enhanced durability. CVC (Chief Value Cotton) fabric offers the perfect balance of softness and performance. Side-seamed with shoulder taping and a modern retail fit. Available in heather color options.',
        'fabric': '32/1 52% Airlume combed and ring-spun cotton 48% polyester; 32/1 90% Airlume combed and ring-spun cotton 10% polyester',
        'fit_guide': 'Unisex sizing, retail fit, side-seamed',
        'size_chart': {
            'XS': {'chest': '16.5', 'length': '28'},
            'S': {'chest': '18', 'length': '29'},
            'M': {'chest': '20', 'length': '30'},
            'L': {'chest': '22', 'length': '31'},
            'XL': {'chest': '24', 'length': '32'},
            '2XL': {'chest': '26', 'length': '33'},
            '3XL': {'chest': '28', 'length': '33'}
        }
    },
    '3501Y': {
        'style_number': '3501Y',
        'description': 'The youth version of the popular 3501 long sleeve tee. Made with 100% Airlume combed and ring-spun cotton for exceptional softness. Sized and fitted for kids. Features side-seamed construction and shoulder-to-shoulder taping. Perfect for youth programs and cooler weather.',
        'fabric': '100% Airlume combed and ring-spun cotton',
        'fit_guide': 'Youth sizing, retail fit, side-seamed',
        'size_chart': {
            'YS': {'chest': '15.25', 'length': '21.125'},
            'YM': {'chest': '16.25', 'length': '22.25'},
            'YL': {'chest': '17.25', 'length': '23.375'}
        }
    },
    '3501YCVC': {
        'style_number': '3501YCVC',
        'description': 'The youth heather jersey long sleeve tee. CVC blend combines cotton comfort with polyester durability. Sized and fitted for kids. Perfect for youth programs, schools, and sports teams in heather colors.',
        'fabric': '52% Airlume combed and ring-spun cotton, 48% polyester; 90% Airlume combed and ring-spun cotton, 10% polyester',
        'fit_guide': 'Youth sizing, retail fit, side-seamed',
        'size_chart': {
            'YS': {'chest': '15.25', 'length': '21.125'},
            'YM': {'chest': '16.25', 'length': '22.25'},
            'YL': {'chest': '17.25', 'length': '23.375'}
        }
    },
    '3513': {
        'style_number': '3513',
        'description': 'The Bella+Canvas 3513 Unisex Triblend Long Sleeve Tee combines polyester, cotton, and rayon for a soft, broken-in feel. Same tri-blend comfort as the 3413 in long sleeve form. Features side-seamed construction and shoulder taping. Perfect for cooler weather with a vintage-inspired look.',
        'fabric': '40/1 50% polyester 25% Airlume combed and ring-spun cotton 25% rayon; 40/1 70% Airlume combed and ring-spun cotton 25% polyester 25% rayon',
        'fit_guide': 'Unisex sizing, relaxed fit, side-seamed',
        'size_chart': {
            'XS': {'chest': '16.5', 'length': '28'},
            'S': {'chest': '18', 'length': '29'},
            'M': {'chest': '20', 'length': '30'},
            'L': {'chest': '22', 'length': '31'},
            'XL': {'chest': '24', 'length': '32'},
            '2XL': {'chest': '26', 'length': '33'},
            '3XL': {'chest': '28', 'length': '33'}
        }
    },
    '3513Y': {
        'style_number': '3513Y',
        'description': 'The youth version of the 3513 Triblend Long Sleeve Tee. Same soft tri-blend fabric sized for kids. Perfect for youth programs and cooler weather.',
        'fabric': '50% polyester, 25% Airlume combed and ring-spun cotton, 25% rayon',
        'fit_guide': 'Youth sizing, relaxed fit, side-seamed',
        'size_chart': {
            'YS': {'chest': '15.25', 'length': '21.125'},
            'YM': {'chest': '16.25', 'length': '22.25'},
            'YL': {'chest': '17.25', 'length': '23.375'}
        }
    },
    '3719': {
        'style_number': '3719',
        'description': 'The Bella+Canvas 3719 Unisex Sponge Fleece Pullover Hoodie features a soft, brushed interior and durable exterior. Made from CVC and cotton blends for warmth and comfort. Includes a lined hood, kangaroo pocket, and matching drawcord. Perfect for casual wear and cooler weather.',
        'fabric': '52% combed and ring-spun cotton, 48% polyester; 90% combed and ring-spun cotton, 10% polyester; 60% combed and ring-spun cotton, 40% polyester; 85% combed and ring-spun cotton, 15% polyester',
        'fit_guide': 'Unisex sizing, relaxed fit, sponge fleece',
        'size_chart': {
            'XS': {'chest': '18', 'length': '25.5'},
            'S': {'chest': '19.5', 'length': '26.375'},
            'M': {'chest': '21.5', 'length': '27.5'},
            'L': {'chest': '23.5', 'length': '28.625'},
            'XL': {'chest': '25.5', 'length': '29.75'},
            '2XL': {'chest': '27.5', 'length': '30.875'},
            '3XL': {'chest': '29.5', 'length': '32'}
        }
    },
    '3719Y': {
        'style_number': '3719Y',
        'description': 'The youth version of the 3719 Sponge Fleece Pullover Hoodie. Same soft sponge fleece construction sized for kids. Features lined hood and kangaroo pocket.',
        'fabric': '52% combed and ring-spun cotton, 48% polyester; 90% combed and ring-spun cotton, 10% polyester',
        'fit_guide': 'Youth sizing, relaxed fit, sponge fleece',
        'size_chart': {
            'YS': {'chest': '16.5', 'length': '21.5'},
            'YM': {'chest': '17.5', 'length': '23'},
            'YL': {'chest': '18.5', 'length': '24'}
        }
    },
    '3729': {
        'style_number': '3729',
        'description': 'The Bella+Canvas 3729 Unisex Sponge Fleece Pullover is a crewneck sweatshirt with the same soft sponge fleece as the hoodie. Brushed interior for warmth, durable exterior. Features side-seamed construction. Perfect for those who prefer a classic crewneck over a hoodie.',
        'fabric': '60% combed and ring-spun cotton, 40% polyester',
        'fit_guide': 'Unisex sizing, relaxed fit, sponge fleece',
        'size_chart': {
            'XS': {'chest': '21.625', 'length': '26.5'},
            'S': {'chest': '23.625', 'length': '27'},
            'M': {'chest': '25', 'length': '28'},
            'L': {'chest': '27.375', 'length': '29.5'},
            'XL': {'chest': '29.375', 'length': '30.5'},
            '2XL': {'chest': '31.375', 'length': '31.5'}
        }
    },
    '3901': {
        'style_number': '3901',
        'description': 'The Bella+Canvas 3901 Unisex Sponge Fleece Raglan Sweatshirt features raglan sleeves for a comfortable, athletic fit. Soft sponge fleece with brushed interior. Full zip front with metal zipper. Available in various CVC and cotton blends. Perfect for layering.',
        'fabric': '32/1 52% combed and ring-spun cotton 48% polyester; 32/1 60% combed and ring-spun cotton 40% polyester; 32/1 90% combed and ring-spun cotton 10% polyester; 30/1 50% polyester 37.5% cotton 12.5% rayon; 30/1 85% combed and ring-spun cotton 15% polyester',
        'fit_guide': 'Unisex sizing, relaxed fit, raglan sleeves, sponge fleece',
        'size_chart': {
            'XS': {'chest': '18.25', 'length': '26.5'},
            'S': {'chest': '19.25', 'length': '27.75'},
            'M': {'chest': '20.25', 'length': '29'},
            'L': {'chest': '21.25', 'length': '30'},
            'XL': {'chest': '22.5', 'length': '31'},
            '2XL': {'chest': '23.75', 'length': '32'},
            '3XL': {'chest': '25.25', 'length': '33'}
        }
    },
    '3901Y': {
        'style_number': '3901Y',
        'description': 'The youth version of the 3901 Sponge Fleece Full-Zip Hoodie. Same raglan construction and soft sponge fleece sized for kids. Full zip front for easy on/off.',
        'fabric': '52% Airlume combed and ring-spun cotton, 48% polyester',
        'fit_guide': 'Youth sizing, relaxed fit, full-zip hoodie, sponge fleece',
        'size_chart': {
            'YS': {'chest': '16.5', 'length': '21.375'},
            'YM': {'chest': '17.5', 'length': '23'},
            'YL': {'chest': '18.5', 'length': '24.125'}
        }
    },
    '3945': {
        'style_number': '3945',
        'description': 'The Bella+Canvas 3945 Unisex Sponge Fleece Drop Shoulder Fleece features a relaxed drop-shoulder design for a modern, oversized look. Soft sponge fleece with brushed interior. Crewneck style. Perfect for a comfortable, casual aesthetic.',
        'fabric': '52% combed and ring-spun cotton, 48% polyester; 90% combed and ring-spun cotton, 10% polyester; 70% combed and ring-spun cotton, 30% polyester',
        'fit_guide': 'Unisex sizing, relaxed drop-shoulder fit, sponge fleece',
        'size_chart': {
            'XS': {'chest': '19.375', 'length': '27.125'},
            'S': {'chest': '21.375', 'length': '27.625'},
            'M': {'chest': '22.75', 'length': '28.25'},
            'L': {'chest': '25.125', 'length': '29.625'},
            'XL': {'chest': '27.125', 'length': '30.625'},
            '2XL': {'chest': '29.125', 'length': '31.625'}
        }
    },
    '4711': {
        'style_number': '4711',
        'description': 'The Bella+Canvas 4711 Unisex 10 oz Crewneck Sweatshirt is a heavyweight classic. Made from 60% cotton, 40% polyester 3-end fleece for maximum warmth and durability. Ribbed cuffs and waistband. All measurements taken flat. A staple for any wardrobe.',
        'fabric': '60% cotton, 40% polyester, 3-end fleece',
        'fit_guide': 'Unisex sizing, relaxed fit, 10 oz heavyweight fleece',
        'size_chart': {
            'XS': {'chest': '20.75', 'length': '26.5'},
            'S': {'chest': '21.5', 'length': '28'},
            'M': {'chest': '23.5', 'length': '28.5'},
            'L': {'chest': '25.5', 'length': '29.5'},
            'XL': {'chest': '27.5', 'length': '30'},
            '2XL': {'chest': '29.5', 'length': '30.5'},
            '3XL': {'chest': '31.5', 'length': '31'},
            '4XL': {'chest': '33.5', 'length': '31.5'}
        }
    },
    '4719': {
        'style_number': '4719',
        'description': 'The Bella+Canvas 4719 Unisex 10 oz Pullover Hoodie is the hooded version of the 4711. Same heavyweight 3-end fleece construction. Features lined hood, kangaroo pocket, and ribbed cuffs/waistband. All measurements taken flat.',
        'fabric': '60% cotton, 40% polyester, 3-end fleece',
        'fit_guide': 'Unisex sizing, relaxed fit, 10 oz heavyweight fleece',
        'size_chart': {
            'XS': {'chest': '20.75', 'length': '26.5'},
            'S': {'chest': '21.5', 'length': '28'},
            'M': {'chest': '23.5', 'length': '28.5'},
            'L': {'chest': '25.5', 'length': '29.5'},
            'XL': {'chest': '27.5', 'length': '30'},
            '2XL': {'chest': '29.5', 'length': '30.5'},
            '3XL': {'chest': '31.5', 'length': '31'},
            '4XL': {'chest': '33.5', 'length': '31.5'}
        }
    },
    '6400': {
        'style_number': '6400',
        'description': "The Bella+Canvas 6400 Women's Relaxed Jersey Short Sleeve Tee is designed for a comfortable, relaxed fit. Made from 100% combed and ring-spun cotton for exceptional softness. Side-seamed construction. A flattering, easy-going option for women's apparel.",
        'fabric': '100% combed and ring-spun cotton',
        'fit_guide': "Women's sizing, relaxed fit, side-seamed",
        'size_chart': {
            'S': {'chest': '18.5', 'length': '25.25'},
            'M': {'chest': '20', 'length': '26'},
            'L': {'chest': '22', 'length': '26.75'},
            'XL': {'chest': '24', 'length': '27.5'},
            '2XL': {'chest': '26', 'length': '28.25'},
            '3XL': {'chest': '28', 'length': '29'}
        }
    }
}
